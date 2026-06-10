$ErrorActionPreference = "Stop"

$AppDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$HtmlPath = Join-Path $AppDir "facilities-manager.html"
$DataDir = Join-Path $AppDir "data"
$StatePath = Join-Path $DataDir "state.json"
$BackupDir = Join-Path $DataDir "backups"
$HostName = if ($env:FM_HOST) { $env:FM_HOST } else { "127.0.0.1" }
$Port = if ($env:FM_PORT) { [int]$env:FM_PORT } else { 8088 }
$AdminUser = if ($env:FM_ADMIN_USER) { $env:FM_ADMIN_USER } else { "admin" }
$AdminPassword = if ($env:FM_ADMIN_PASSWORD) { $env:FM_ADMIN_PASSWORD } else { "ChangeMe123!" }
$Sessions = @{}

New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null

function Write-Response {
  param(
    [System.Net.HttpListenerContext]$Context,
    [string]$Body,
    [string]$ContentType = "text/html; charset=utf-8",
    [int]$StatusCode = 200,
    [hashtable]$Headers = @{}
  )
  $bytes = [System.Text.Encoding]::UTF8.GetBytes($Body)
  $Context.Response.StatusCode = $StatusCode
  $Context.Response.ContentType = $ContentType
  $Context.Response.ContentLength64 = $bytes.Length
  $Context.Response.Headers["Cache-Control"] = "no-store"
  foreach ($key in $Headers.Keys) {
    $Context.Response.Headers[$key] = $Headers[$key]
  }
  $Context.Response.OutputStream.Write($bytes, 0, $bytes.Length)
  $Context.Response.Close()
}

function Read-Body {
  param([System.Net.HttpListenerRequest]$Request)
  $reader = New-Object System.IO.StreamReader($Request.InputStream, $Request.ContentEncoding)
  try { $reader.ReadToEnd() } finally { $reader.Close() }
}

function Parse-Form {
  param([string]$Body)
  $result = @{}
  foreach ($pair in $Body -split "&") {
    if (-not $pair) { continue }
    $parts = $pair -split "=", 2
    $key = [System.Uri]::UnescapeDataString($parts[0].Replace("+", " "))
    $value = if ($parts.Count -gt 1) { [System.Uri]::UnescapeDataString($parts[1].Replace("+", " ")) } else { "" }
    $result[$key] = $value
  }
  $result
}

function Get-SessionToken {
  param([System.Net.HttpListenerRequest]$Request)
  $cookie = $Request.Cookies["fm_session"]
  if ($cookie) { $cookie.Value } else { "" }
}

function Is-LoggedIn {
  param([System.Net.HttpListenerRequest]$Request)
  $token = Get-SessionToken $Request
  $token -and $Sessions.ContainsKey($token) -and $Sessions[$token] -gt (Get-Date)
}

function Redirect {
  param([System.Net.HttpListenerContext]$Context, [string]$Location)
  $Context.Response.StatusCode = 302
  $Context.Response.RedirectLocation = $Location
  $Context.Response.Close()
}

function Send-Login {
  param([System.Net.HttpListenerContext]$Context)
  Write-Response $Context @"
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Facilities Manager Login</title>
  <style>
    body { margin: 0; min-height: 100vh; display: grid; place-items: center; font-family: Arial, Helvetica, sans-serif; background: #f6f5f1; color: #202327; }
    form { width: min(380px, calc(100vw - 28px)); background: #fff; border: 1px solid #d9ddd4; border-radius: 8px; padding: 22px; box-shadow: 0 8px 28px rgba(33,37,41,.08); display: grid; gap: 12px; }
    h1 { margin: 0 0 4px; font-size: 24px; }
    p { margin: 0 0 12px; color: #6b7280; font-size: 14px; }
    label { display: grid; gap: 6px; font-size: 13px; font-weight: 700; }
    input { min-height: 40px; border: 1px solid #cfd5cc; border-radius: 8px; padding: 9px 10px; font: inherit; }
    button { min-height: 40px; border: 0; border-radius: 8px; background: #2f6f4e; color: #fff; font: inherit; cursor: pointer; }
    .hint { color: #6b7280; font-size: 12px; line-height: 1.4; }
  </style>
</head>
<body>
  <form method="post" action="/login">
    <h1>Facilities Manager</h1>
    <p>Sign in to the shared business system.</p>
    <label>Username<input name="username" autocomplete="username" required></label>
    <label>Password<input name="password" type="password" autocomplete="current-password" required></label>
    <button type="submit">Sign in</button>
    <div class="hint">First run default: $AdminUser / $AdminPassword. You can change this in the start script environment.</div>
  </form>
</body>
</html>
"@
}

function Get-StateJson {
  if (Test-Path $StatePath) {
    Get-Content -LiteralPath $StatePath -Raw
  } else {
    ""
  }
}

function Send-App {
  param([System.Net.HttpListenerContext]$Context)
  $html = Get-Content -LiteralPath $HtmlPath -Raw
  $state = Get-StateJson
  if ([string]::IsNullOrWhiteSpace($state)) { $state = "null" }
  $bootstrap = @"
<script>
  window.__FM_SERVER_MODE__ = true;
  window.__FM_SERVER_STATE__ = $state;
  (function () {
    const syncKey = 'facilities-manager-v1';
    if (window.__FM_SERVER_STATE__) {
      localStorage.setItem(syncKey, JSON.stringify(window.__FM_SERVER_STATE__));
    }
    const originalSetItem = localStorage.setItem.bind(localStorage);
    let syncTimer = null;
    localStorage.setItem = function (key, value) {
      originalSetItem(key, value);
      if (key !== syncKey) return;
      clearTimeout(syncTimer);
      syncTimer = setTimeout(function () {
        fetch('/api/state', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: value
        }).catch(function () {});
      }, 250);
    };
  })();
</script>
"@
  $html = $html.Replace("<script>`r`n    const storeKey", "$bootstrap`r`n  <script>`r`n    const storeKey")
  $html = $html.Replace("<script>`n    const storeKey", "$bootstrap`n  <script>`n    const storeKey")
  $html = $html.Replace('<button class="btn" id="importData">', '<a class="btn" href="/api/backup" style="text-decoration:none;">Server Backup</a><a class="btn" href="/logout" style="text-decoration:none;">Sign out</a><button class="btn" id="importData">')
  Write-Response $Context $html
}

function Save-State {
  param([System.Net.HttpListenerContext]$Context)
  $body = Read-Body $Context.Request
  try {
    $null = $body | ConvertFrom-Json
  } catch {
    Write-Response $Context '{"ok":false,"error":"Invalid JSON"}' "application/json; charset=utf-8" 400
    return
  }
  Set-Content -LiteralPath $StatePath -Value $body -Encoding UTF8
  $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
  Set-Content -LiteralPath (Join-Path $BackupDir "backup-$stamp.json") -Value $body -Encoding UTF8
  Write-Response $Context '{"ok":true}' "application/json; charset=utf-8"
}

function Send-Backup {
  param([System.Net.HttpListenerContext]$Context)
  $state = Get-StateJson
  if ([string]::IsNullOrWhiteSpace($state)) { $state = "{}" }
  $filename = "facilities-backup-{0}.json" -f (Get-Date -Format "yyyyMMdd-HHmmss")
  Write-Response $Context $state "application/json; charset=utf-8" 200 @{ "Content-Disposition" = "attachment; filename=`"$filename`"" }
}

$listener = New-Object System.Net.HttpListener
$prefix = "http://${HostName}:${Port}/"
$listener.Prefixes.Add($prefix)
$listener.Start()

Write-Host "Facilities Manager running at $prefix"
Write-Host "Login: $AdminUser / $AdminPassword"
Write-Host "Keep this window open while using the system."

try {
  while ($listener.IsListening) {
    $context = $listener.GetContext()
    $path = $context.Request.Url.AbsolutePath
    $method = $context.Request.HttpMethod

    if ($method -eq "GET" -and $path -eq "/login") {
      Send-Login $context
      continue
    }

    if ($method -eq "POST" -and $path -eq "/login") {
      $form = Parse-Form (Read-Body $context.Request)
      if ($form["username"] -eq $AdminUser -and $form["password"] -eq $AdminPassword) {
        $token = [Guid]::NewGuid().ToString("N")
        $Sessions[$token] = (Get-Date).AddHours(12)
        $cookie = New-Object System.Net.Cookie("fm_session", $token, "/")
        $context.Response.Cookies.Add($cookie)
        Redirect $context "/"
      } else {
        Redirect $context "/login"
      }
      continue
    }

    if ($method -eq "GET" -and $path -eq "/logout") {
      $token = Get-SessionToken $context.Request
      if ($token) { $Sessions.Remove($token) }
      $cookie = New-Object System.Net.Cookie("fm_session", "", "/")
      $cookie.Expires = (Get-Date).AddDays(-1)
      $context.Response.Cookies.Add($cookie)
      Redirect $context "/login"
      continue
    }

    if (-not (Is-LoggedIn $context.Request)) {
      Redirect $context "/login"
      continue
    }

    if ($method -eq "GET" -and ($path -eq "/" -or $path -eq "/facilities-manager.html")) {
      Send-App $context
    } elseif ($method -eq "GET" -and $path -eq "/api/state") {
      $state = Get-StateJson
      if ([string]::IsNullOrWhiteSpace($state)) { $state = "null" }
      Write-Response $context $state "application/json; charset=utf-8"
    } elseif ($method -eq "POST" -and $path -eq "/api/state") {
      Save-State $context
    } elseif ($method -eq "GET" -and $path -eq "/api/backup") {
      Send-Backup $context
    } else {
      Write-Response $context "Not found" "text/plain; charset=utf-8" 404
    }
  }
} finally {
  $listener.Stop()
}

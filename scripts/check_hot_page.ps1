$session = New-Object Microsoft.PowerShell.Commands.WebRequestSession

# Prime cookies + CSRF
Invoke-WebRequest -Uri "http://127.0.0.1:8765/admin/login" -WebSession $session -UseBasicParsing | Out-Null

# Try logging in (admin/admin is the dev default; if it fails the page checks still work for HTML structure)
try {
    Invoke-WebRequest `
        -Uri "http://127.0.0.1:8765/admin/login" `
        -Method POST `
        -Body @{ username = "admin"; password = "admin" } `
        -WebSession $session `
        -UseBasicParsing `
        -MaximumRedirection 0 `
        -ErrorAction SilentlyContinue | Out-Null
} catch {
    Write-Host "login error (continuing): $($_.Exception.Message)"
}

$page = Invoke-WebRequest `
    -Uri "http://127.0.0.1:8765/admin/hot/cybersport" `
    -WebSession $session -UseBasicParsing -MaximumRedirection 0 -ErrorAction SilentlyContinue
Write-Host "page status: $($page.StatusCode), bytes: $($page.RawContentLength)"

$html = $page.Content

Write-Host ""
Write-Host "=== fix checks in rendered HTML ==="
$pat1 = 'x-cloak'
$pat2 = 'x-show="loading" style="display:none"'
$pat3 = 'x-show="searching" style="display:none"'
$pat4 = 'console.error'
$pat5 = '\[x-cloak\] \{ display: none !important; \}'

Write-Host ("  x-cloak directive present:     {0}" -f ($html -match $pat1))
Write-Host ("  Loading has display:none:      {0}" -f ($html -match [regex]::Escape($pat2)))
Write-Host ("  Searching has display:none:    {0}" -f ($html -match [regex]::Escape($pat3)))
Write-Host ("  console.error logging present: {0}" -f ($html -match $pat4))
Write-Host ("  x-cloak CSS rule in base.html: {0}" -f ($html -match $pat5))

$ErrorActionPreference = "Stop"

$Version = "v2.0.2"
$Asset = "github-mcp-server_Windows_x86_64.zip"
$Sha256 = "4ae64087501650752f21c9d5af5378107a5116d94ee1cf37786b22b8c4bd99df"
$Url = "https://github.com/github/github-mcp-server/releases/download/$Version/$Asset"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$ToolsDir = Join-Path $Root "tools"
$ExePath = Join-Path $ToolsDir "github-mcp-server.exe"

if (Test-Path -LiteralPath $ExePath) {
    Write-Host "github-mcp-server.exe already installed: $ExePath"
    exit 0
}

New-Item -ItemType Directory -Path $ToolsDir -Force | Out-Null

$ZipPath = Join-Path $ToolsDir $Asset
Write-Host "Downloading $Asset ..."
Invoke-WebRequest -Uri $Url -OutFile $ZipPath -UseBasicParsing

Write-Host "Verifying sha256 ..."
$Hash = (Get-FileHash -LiteralPath $ZipPath -Algorithm SHA256).Hash.ToLower()
if ($Hash -ne $Sha256) {
    Remove-Item -LiteralPath $ZipPath -Force
    throw "sha256 mismatch: got $Hash, expected $Sha256"
}

Write-Host "Extracting ..."
Expand-Archive -LiteralPath $ZipPath -DestinationPath $ToolsDir -Force
Remove-Item -LiteralPath $ZipPath -Force

if (-not (Test-Path -LiteralPath $ExePath)) {
    $found = Get-ChildItem -LiteralPath $ToolsDir -Filter "github-mcp-server*.exe" -Recurse | Select-Object -First 1
    if ($found) {
        Move-Item -LiteralPath $found.FullName -Destination $ExePath -Force
    }
}

if (-not (Test-Path -LiteralPath $ExePath)) {
    throw "github-mcp-server.exe not found after extraction"
}

Write-Host "Done: $ExePath"

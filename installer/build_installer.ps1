[CmdletBinding()]
param(
    [string]$PythonExe = "python",
    [string]$IsccPath = ""
)

$ErrorActionPreference = "Stop"
$InstallerDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $InstallerDir
Set-Location $ProjectRoot

$index = Join-Path $ProjectRoot "generated\semantic_index.sqlite"
$manifest = Join-Path $ProjectRoot "generated\index_manifest.json"
if (!(Test-Path $index) -or !(Test-Path $manifest)) {
    throw "The generated SQLite index and manifest are required before packaging."
}

Write-Host "Checking the source index..."
& $PythonExe -c "import json,sqlite3,sys; m=json.load(open(sys.argv[1],encoding='utf-8')); c=sqlite3.connect(sys.argv[2]); assert c.execute('select count(*) from evidence').fetchone()[0] == m['evidence_count']; assert c.execute('select count(*) from author_periods').fetchone()[0] == m['author_period_count']; print('Source index verified')" $manifest $index
if ($LASTEXITCODE -ne 0) { throw "Source index validation failed." }

Remove-Item -Recurse -Force (Join-Path $ProjectRoot "build\TheologiaSearch") -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force (Join-Path $ProjectRoot "dist\TheologiaSearch") -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force (Join-Path $ProjectRoot "release") -ErrorAction SilentlyContinue

Write-Host "Building the self-contained application..."
& $PythonExe -m PyInstaller --noconfirm --clean (Join-Path $InstallerDir "TheologiaSearch.spec")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed." }

Write-Host "Verifying the packaged payload..."
& $PythonExe (Join-Path $InstallerDir "verify_package.py") (Join-Path $ProjectRoot "dist\TheologiaSearch")
if ($LASTEXITCODE -ne 0) { throw "Packaged payload validation failed." }

Write-Host "Running the packaged startup smoke test..."
$packagedExe = Join-Path $ProjectRoot "dist\TheologiaSearch\TheologiaSearch.exe"
& $packagedExe --self-test
if ($LASTEXITCODE -ne 0) { throw "Packaged startup smoke test failed." }

if (!$IsccPath) {
    $candidates = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles}\Inno Setup 6\ISCC.exe",
        "${env:LOCALAPPDATA}\Programs\Inno Setup 6\ISCC.exe"
    )
    $IsccPath = $candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
}
if (!$IsccPath -or !(Test-Path $IsccPath)) {
    throw "Inno Setup 6 ISCC.exe was not found. Install Inno Setup 6 on the build machine or pass -IsccPath."
}

Write-Host "Creating the single installer executable..."
& $IsccPath (Join-Path $InstallerDir "TheologiaSearch.iss")
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed." }

Write-Host "Created: $ProjectRoot\release\Theologia Search Setup.exe"

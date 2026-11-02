# Asentaa dist\Opintolainalaskuri -kansion käyttäjälle ja tekee pikakuvakkeet
# työpöydälle ja Käynnistä-valikkoon. Ajetaan Rakenna_exe.bat-tiedostosta.
$ErrorActionPreference = "Stop"
$name = "Opintolainalaskuri"
$src  = Join-Path $PSScriptRoot "dist\$name"
$dst  = Join-Path $env:LOCALAPPDATA "Programs\$name"
$exe  = Join-Path $dst "$name.exe"

if (-not (Test-Path (Join-Path $src "$name.exe"))) { throw "Rakennettua sovellusta ei löydy: $src" }
if (Get-Process -Name $name -ErrorAction SilentlyContinue) { throw "Sulje Opintolainalaskuri ennen asennusta." }

if (Test-Path $dst) { Remove-Item $dst -Recurse -Force }
New-Item -ItemType Directory -Force (Split-Path $dst) | Out-Null
Copy-Item $src $dst -Recurse

$sh = New-Object -ComObject WScript.Shell
foreach ($dir in @([Environment]::GetFolderPath("Desktop"), [Environment]::GetFolderPath("Programs"))) {
    $lnkPath = Join-Path $dir "$name.lnk"
    $lnk = $sh.CreateShortcut($lnkPath)
    $lnk.TargetPath = $exe
    $lnk.WorkingDirectory = $dst
    $lnk.IconLocation = "$exe,0"
    $lnk.Description = "Opintolainojen vertailu: Nordea, Danske Bank ja OP"
    $lnk.Save()
    Write-Output "Pikakuvake: $lnkPath"
}
Write-Output "Asennettu: $exe"

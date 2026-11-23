[CmdletBinding()]
param(
    [string]$Gradle = 'gradle.bat'
)

$ErrorActionPreference = 'Stop'
$gradleCommand = Get-Command $Gradle -CommandType Application -ErrorAction SilentlyContinue
if (-not $gradleCommand) {
    throw 'Gradle not found. Add Gradle 8.9 to PATH or pass -Gradle C:\path\to\gradle.bat.'
}

& $gradleCommand.Source -p $PSScriptRoot --no-daemon testDebugUnitTest lintDebug assembleDebug
if ($LASTEXITCODE -ne 0) {
    throw "Android build failed with exit code $LASTEXITCODE."
}

$apk = Join-Path $PSScriptRoot 'app\build\outputs\apk\debug\app-debug.apk'
if (-not (Test-Path -LiteralPath $apk -PathType Leaf)) {
    throw "Expected debug APK was not generated: $apk"
}

Write-Output "Debug APK: $apk"

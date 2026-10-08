param(
    [ValidateSet('Debug', 'Release')][string]$Variant = 'Debug',
    [switch]$SkipChecks
)
$ErrorActionPreference = 'Stop'
$projectDirectory = $PSScriptRoot
$jdkCandidates = @(
    $env:JAVA_HOME,
    (Join-Path $env:USERPROFILE '.jdks\jbr-21.0.11'),
    (Join-Path $env:ProgramFiles 'Android\Android Studio\jbr')
)
$jdkDirectory = $jdkCandidates | Where-Object {
    $_ -and (Test-Path -LiteralPath (Join-Path $_ 'bin\javac.exe'))
} | Select-Object -First 1
if (-not $jdkDirectory) { throw 'Set JAVA_HOME to a JDK 17 or 21 (a JRE cannot build Android apps).' }
$env:JAVA_HOME = $jdkDirectory
$sdkDirectory = $env:ANDROID_HOME
if (-not $sdkDirectory) { $sdkDirectory = $env:ANDROID_SDK_ROOT }
if (-not $sdkDirectory) { $sdkDirectory = Join-Path $env:LOCALAPPDATA 'Android\Sdk' }
$localProperties = Join-Path $projectDirectory 'local.properties'
if (-not (Test-Path -LiteralPath $localProperties)) {
    if (-not (Test-Path -LiteralPath $sdkDirectory)) { throw 'Set ANDROID_HOME to your existing Android SDK.' }
    $sdkProperty = $sdkDirectory.Replace('\', '/').Replace(':', '\:')
    [IO.File]::WriteAllText($localProperties, "sdk.dir=$sdkProperty`n", [Text.Encoding]::ASCII)
}
$tasks = @("assemble$Variant")
if (-not $SkipChecks) { $tasks += @("test${Variant}UnitTest", "lint$Variant") }
Push-Location $projectDirectory
try {
    & .\gradlew.bat @tasks --console=plain
    if ($LASTEXITCODE -ne 0) { throw "Android build failed (exit $LASTEXITCODE)." }
    $apkDirectory = Join-Path $projectDirectory ('app\build\outputs\apk\' + $Variant.ToLower())
    $apk = Get-ChildItem -LiteralPath $apkDirectory -Filter '*.apk' | Select-Object -First 1
    if (-not $apk) { throw 'The build did not produce an APK.' }
    $destinationDirectory = Join-Path (Split-Path $projectDirectory -Parent) 'dist'
    New-Item -ItemType Directory -Path $destinationDirectory -Force | Out-Null
    $versionFile = Join-Path (Split-Path $projectDirectory -Parent) 'update_check.py'
    $versionMatch = [regex]::Match([IO.File]::ReadAllText($versionFile), '(?m)^VERSION = "([^"]+)"')
    $suffix = if ($apk.Name -match 'unsigned') { '-release-unsigned' } elseif ($Variant -eq 'Debug') { '-debug' } else { '' }
    $destination = Join-Path $destinationDirectory ('watch2notif-android-' + $versionMatch.Groups[1].Value + $suffix + '.apk')
    Copy-Item -LiteralPath $apk.FullName -Destination $destination -Force
    Write-Output "APK: $destination"
} finally { Pop-Location }

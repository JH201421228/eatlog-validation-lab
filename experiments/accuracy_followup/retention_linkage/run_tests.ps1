$ErrorActionPreference = 'Stop'
$beRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../../../BE'))
$testCwd = Join-Path ([IO.Path]::GetTempPath()) ('eatlog-linkage-' + [guid]::NewGuid())
New-Item -ItemType Directory -Path $testCwd | Out-Null
$testEnv = @{
    PYTHONPATH = $beRoot
    DATABASE_URL = 'sqlite://'
    AI_CLIENT_MODE = 'mock'
    RUN_MIGRATIONS_ON_STARTUP = 'false'
    REQUEST_LOG_ENABLED = 'false'
    IMAGE_RETENTION_PURGE_ENABLED = 'false'
    WEEKLY_REPORT_PUSH_ENABLED = 'false'
    LIFECYCLE_PUSH_ENABLED = 'false'
}
$savedEnv = @{}
foreach ($key in $testEnv.Keys) {
    $savedEnv[$key] = [Environment]::GetEnvironmentVariable($key, 'Process')
    [Environment]::SetEnvironmentVariable($key, $testEnv[$key], 'Process')
}
Push-Location -LiteralPath $testCwd
try {
    & (Join-Path $beRoot 'venv/Scripts/python.exe') -m pytest "--rootdir=$beRoot" `
        "--confcutdir=$beRoot/tests" "$beRoot/tests/test_meal_analytics_fields.py" `
        "$beRoot/tests/test_meals.py" "$beRoot/tests/test_multi_image_api.py" `
        -q -p no:cacheprovider --tb=short
    $testExit = $LASTEXITCODE
}
finally {
    Pop-Location
    foreach ($key in $savedEnv.Keys) {
        [Environment]::SetEnvironmentVariable($key, $savedEnv[$key], 'Process')
    }
}
exit $testExit

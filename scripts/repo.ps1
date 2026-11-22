param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("help", "setup", "install", "run", "test", "lint", "build", "model", "doctor", "clean")]
    [string]$Task,
    [ValidateNotNullOrEmpty()]
    [string]$Venv = ".venv",
    [string]$Python = "",
    [ValidateSet("base", "small", "medium")]
    [string]$Model = "small",
    [string]$BundleModel = ""
)
$ErrorActionPreference = "Stop"
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
Set-Location -LiteralPath $root
$venvDirectory = if ([IO.Path]::IsPathRooted($Venv)) {
    [IO.Path]::GetFullPath($Venv)
} else {
    [IO.Path]::GetFullPath((Join-Path $root $Venv))
}
$venvPython = Join-Path $venvDirectory "Scripts\python.exe"
$script:failureCode = 1

function Invoke-Checked([string]$Executable, [string[]]$Arguments) {
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        $script:failureCode = $LASTEXITCODE
        throw "Command failed with exit code ${LASTEXITCODE}: $Executable"
    }
}

function Require-Environment {
    if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
        throw "Virtual environment not found: $venvDirectory. Run make install first."
    }
}

function Initialize-Environment {
    if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
        if (Test-Path -LiteralPath $venvDirectory) {
            $item = Get-Item -LiteralPath $venvDirectory -Force
            if (-not $item.PSIsContainer -or
                @(Get-ChildItem -LiteralPath $venvDirectory -Force).Count -gt 0) {
                throw "Refusing to create a virtual environment in a non-empty folder: $venvDirectory"
            }
        }
        $bootstrap = $Python
        $bootstrapArgs = @()
        if (-not $bootstrap) {
            $existing = Join-Path $root ".venv\Scripts\python.exe"
            if (Test-Path -LiteralPath $existing -PathType Leaf) {
                $bootstrap = $existing
            } elseif (Get-Command py.exe -ErrorAction SilentlyContinue) {
                $bootstrap = "py.exe"
                $bootstrapArgs = @("-3.11")
            } else {
                $bootstrap = "python.exe"
            }
        }
        Invoke-Checked $bootstrap ($bootstrapArgs + @(
            "-c", "import sys; assert sys.version_info >= (3, 11), 'Python 3.11+ is required'"
        ))
        Invoke-Checked $bootstrap ($bootstrapArgs + @("-m", "venv", $venvDirectory))
    }
    # uv-created environments can exist without pip. Bootstrap it locally if needed.
    & $venvPython -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('pip') else 1)"
    if ($LASTEXITCODE -ne 0) {
        Invoke-Checked $venvPython @("-m", "ensurepip", "--upgrade")
    }
    Write-Host "Virtual environment ready: $venvDirectory"
}

function Clear-GeneratedFiles {
    $directories = @(
        "build", ".pytest_cache", ".ruff_cache", "__pycache__",
        "src\__pycache__", "src\models\__pycache__", "src\services\__pycache__",
        "src\ui\__pycache__", "src\workers\__pycache__",
        "scripts\__pycache__", "tests\__pycache__"
    )
    # Check every existing path component, not only the leaf, to reject junctions.
    foreach ($relative in $directories) {
        $path = $root
        foreach ($component in ($relative -split '\\')) {
            $path = Join-Path $path $component
            if (Test-Path -LiteralPath $path) {
                $item = Get-Item -LiteralPath $path -Force
                if (-not $item.PSIsContainer -or
                    ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
                    throw "Refusing to clean a file or linked directory: $path"
                }
            }
        }
    }
    foreach ($relative in $directories) {
        $path = Join-Path $root $relative
        if (Test-Path -LiteralPath $path) {
            $pending = New-Object "System.Collections.Generic.Queue[string]"
            $pending.Enqueue($path)
            while ($pending.Count -gt 0) {
                foreach ($item in (Get-ChildItem -LiteralPath $pending.Dequeue() -Force)) {
                    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                        throw "Refusing to clean a linked directory or file: $($item.FullName)"
                    }
                    if ($item.PSIsContainer) { $pending.Enqueue($item.FullName) }
                }
            }
        }
    }
    foreach ($relative in $directories) {
        $path = Join-Path $root $relative
        if (Test-Path -LiteralPath $path) {
            Remove-Item -LiteralPath $path -Recurse -Force
            Write-Host "Removed: $relative"
        }
    }
    Write-Host "Kept dist, models, output, virtual environments, and original recordings."
}

try {
    switch ($Task) {
        "help" {
            Write-Host @"
AI Audio Sentence Splitter - repository commands

  make install     Create/reuse the virtual environment and install development dependencies
  make setup       Create/reuse the virtual environment and ensure pip is available
  make run         Launch the desktop application
  make test        Run the automated test suite
  make lint        Run Ruff without changing files
  make check       Run lint and tests
  make build       Build the Windows release, including its existing validation steps
  make model       Download the small model; MODEL=base or MODEL=medium also supported
  make doctor      Check Python, dependencies, FFmpeg, and FFprobe
  make clean       Remove build/cache directories, keeping releases and user audio/output

Options:
  VENV=.venv               Virtual environment folder
  PYTHON=C:/Python311/python.exe   Bootstrap Python for a new environment
  MODEL=small              Model to download
  BUNDLE_MODEL=models/small Optional small model folder to include in the release
"@
        }
        "setup" { Initialize-Environment }
        "install" {
            Require-Environment
            Invoke-Checked $venvPython @("-m", "pip", "install", "-r", (Join-Path $root "requirements-dev.txt"))
        }
        "run" {
            Require-Environment
            Invoke-Checked $venvPython @((Join-Path $root "app.py"))
        }
        "test" {
            Require-Environment
            Invoke-Checked $venvPython @("-m", "pytest", "-q")
        }
        "lint" {
            Require-Environment
            Invoke-Checked $venvPython @("-m", "ruff", "check", "app.py", "src", "tests", "scripts")
        }
        "build" {
            Require-Environment
            $parameters = @{ Python = $venvPython }
            if ($BundleModel) { $parameters.BundleModel = $BundleModel }
            & (Join-Path $root "build_windows.ps1") @parameters
            if ($LASTEXITCODE -ne 0) {
                $script:failureCode = $LASTEXITCODE
                throw "Windows build failed with exit code $LASTEXITCODE."
            }
        }
        "model" {
            Require-Environment
            Invoke-Checked $venvPython @((Join-Path $root "scripts\download_model.py"), $Model)
        }
        "doctor" {
            Require-Environment
            Invoke-Checked $venvPython @("--version")
            Invoke-Checked $venvPython @("-c", @"
import importlib.util, sys
packages = ['PySide6', 'faster_whisper', 'numpy', 'platformdirs', 'pytest', 'ruff', 'PyInstaller']
missing = [name for name in packages if importlib.util.find_spec(name) is None]
print('Missing dependencies: ' + ', '.join(missing) if missing else 'All dependencies available')
sys.exit(bool(missing))
"@)
            Invoke-Checked $venvPython @("-c", @"
from src.services.audio_service import tool_path
print('FFmpeg: ' + tool_path('ffmpeg'))
print('FFprobe: ' + tool_path('ffprobe'))
"@)
        }
        "clean" { Clear-GeneratedFiles }
    }
} catch {
    Write-Error $_ -ErrorAction Continue
    exit $script:failureCode
}

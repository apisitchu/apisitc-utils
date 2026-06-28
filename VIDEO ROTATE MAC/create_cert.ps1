# ==================================================
#  Create Self-Signed Code Signing Certificate
#  Publisher: running.in.th
# ==================================================
# Run once before building:
#   Right-click → Run with PowerShell
#   OR: powershell -ExecutionPolicy Bypass -File create_cert.ps1
# ==================================================

$certSubject = "CN=running.in.th, O=running.in.th, C=TH"
$pfxPath     = Join-Path $PSScriptRoot "signing_cert.pfx"
$years       = 5

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  Create Code Signing Certificate - running.in.th" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""

if (Test-Path $pfxPath) {
    Write-Host "[INFO] signing_cert.pfx already exists." -ForegroundColor Yellow
    $overwrite = Read-Host "Overwrite? (y/N)"
    if ($overwrite -ne "y" -and $overwrite -ne "Y") {
        Write-Host "Cancelled." -ForegroundColor Gray
        Read-Host "Press Enter to exit"
        exit 0
    }
}

$password = Read-Host "Set a password for signing_cert.pfx" -AsSecureString
$confirm  = Read-Host "Confirm password" -AsSecureString

$p1 = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($password))
$p2 = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($confirm))

if ($p1 -ne $p2) {
    Write-Host "[ERROR] Passwords do not match." -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host ""
Write-Host "[1/2] Creating certificate..." -ForegroundColor Green

try {
    $cert = New-SelfSignedCertificate `
        -Subject $certSubject `
        -Type CodeSigning `
        -CertStoreLocation "Cert:\CurrentUser\My" `
        -HashAlgorithm SHA256 `
        -KeyUsage DigitalSignature `
        -NotAfter (Get-Date).AddYears($years)

    Write-Host "      Thumbprint : $($cert.Thumbprint)"
    Write-Host "      Valid until: $($cert.NotAfter.ToString('yyyy-MM-dd'))"
} catch {
    Write-Host "[ERROR] Failed to create certificate: $_" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host "[2/2] Exporting to signing_cert.pfx..." -ForegroundColor Green

try {
    Export-PfxCertificate -Cert $cert -FilePath $pfxPath -Password $password | Out-Null
    Write-Host ""
    Write-Host "Done! signing_cert.pfx created." -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Next step: run build.bat to build and sign the .exe"
    Write-Host ""
    Write-Host "NOTE: Windows SmartScreen will still show a blue warning" -ForegroundColor Yellow
    Write-Host "      because this is a self-signed (untrusted) certificate." -ForegroundColor Yellow
    Write-Host "      Users click 'More info' -> 'Run anyway' to proceed." -ForegroundColor Yellow
    Write-Host "      For zero-warning, use a commercial cert from DigiCert/Sectigo." -ForegroundColor Yellow
} catch {
    Write-Host "[ERROR] Failed to export .pfx: $_" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host ""
Read-Host "Press Enter to exit"

$vars = @{
    "DB_HOST"     = "aws-1-ap-south-1.pooler.supabase.com"
    "DB_USER"     = "postgres.tikjoirwxeabpodstbce"
    "DB_PASSWORD" = "Navaneeth@12"
    "DB_PORT"     = "6543"
    "DB_NAME"     = "postgres"
}

foreach ($key in $vars.Keys) {
    $val = $vars[$key]
    $tmp = [System.IO.Path]::GetTempFileName()
    # Write WITHOUT any newline
    [System.IO.File]::WriteAllText($tmp, $val)
    Write-Host "Setting $key = $val"
    Get-Content $tmp -Raw | vercel env add $key production --yes
    Remove-Item $tmp
    Write-Host "Done $key"
}
Write-Host "All env vars set successfully!"

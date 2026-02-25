# Use Vercel REST API to set env vars without newlines
$token = "vca_3dWRfB81IMn83nWJnNBaEGTVosEGF7asuWSTgM0kAnEVGI1XAv3lmdiN"
$projectName = "chatbot"
$teamSlug = "navaneeths-projects-3072cc94"

# First get project ID
$projectUrl = "https://api.vercel.com/v9/projects/$projectName`?teamId=$teamSlug"
$project = Invoke-RestMethod -Uri $projectUrl -Headers @{Authorization="Bearer $token"} -Method GET
$projectId = $project.id
Write-Host "Project ID: $projectId"

# Delete existing DB_* vars first
$envVars = Invoke-RestMethod -Uri "https://api.vercel.com/v9/projects/$projectId/env?teamId=$teamSlug" -Headers @{Authorization="Bearer $token"} -Method GET
foreach ($env in $envVars.envs) {
    if ($env.key -like "DB_*") {
        Write-Host "Deleting $($env.key) ($($env.id))"
        Invoke-RestMethod -Uri "https://api.vercel.com/v9/projects/$projectId/env/$($env.id)?teamId=$teamSlug" -Headers @{Authorization="Bearer $token"} -Method DELETE
    }
}

# Add fresh env vars
$vars = @(
    @{key="DB_HOST"; value="aws-1-ap-south-1.pooler.supabase.com"},
    @{key="DB_USER"; value="postgres.tikjoirwxeabpodstbce"},
    @{key="DB_PASSWORD"; value="Navaneeth@12"},
    @{key="DB_PORT"; value="6543"},
    @{key="DB_NAME"; value="postgres"}
)

foreach ($v in $vars) {
    $body = @{
        key    = $v.key
        value  = $v.value
        type   = "encrypted"
        target = @("production","preview","development")
    } | ConvertTo-Json
    $result = Invoke-RestMethod -Uri "https://api.vercel.com/v10/projects/$projectId/env?teamId=$teamSlug" -Headers @{Authorization="Bearer $token"; "Content-Type"="application/json"} -Method POST -Body $body
    Write-Host "Set $($v.key) = $($v.value)  -> id: $($result.id)"
}
Write-Host "All done!"

# Prints one JSON object per second for the current Windows media session.
# The visualizer uses it the way Linux uses MPRIS. Failure here does not stop audio.
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)

function Await-WinRT($operation, $resultType) {
    $method = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
        $_.Name -eq "AsTask" -and $_.IsGenericMethod -and $_.GetParameters().Count -eq 1 -and
        $_.GetParameters()[0].ParameterType.Name -eq "IAsyncOperation``1"
    } | Select-Object -First 1
    $task = $method.MakeGenericMethod($resultType).Invoke($null, @($operation))
    $task.Wait()
    return $task.Result
}

Add-Type -AssemblyName System.Runtime.WindowsRuntime | Out-Null
$null = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager, Windows.Media.Control, ContentType = WindowsRuntime]
$managerType = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager]
$propsType = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionMediaProperties]
$manager = Await-WinRT ($managerType::RequestAsync()) $managerType

while ($true) {
    try {
        $session = $manager.GetCurrentSession()
        $title = ""
        $artist = ""
        $status = ""
        $id = ""
        if ($null -ne $session) {
            $props = Await-WinRT ($session.TryGetMediaPropertiesAsync()) $propsType
            if ($null -ne $props) {
                $title = [string]$props.Title
                $artist = [string]$props.Artist
            }
            $info = $session.GetPlaybackInfo()
            if ($null -ne $info) { $status = [string]$info.PlaybackStatus }
            if ($title -or $artist) { $id = "$artist|$title" }
        }
        [pscustomobject]@{
            id     = $id
            title  = $title
            artist = $artist
            status = $status
        } | ConvertTo-Json -Compress
    } catch {
        Write-Output '{"id":"","title":"","artist":"","status":""}'
    }
    [Console]::Out.Flush()
    Start-Sleep -Seconds 1
}

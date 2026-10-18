<#
Connect a USB-attached phone to the adb server inside the Docker `appium` container
(Docker Desktop on Windows/macOS cannot pass USB through). Uses the host adb to
switch the phone to adb-over-TCP, then connects from the container and records the
target in the adb-keys volume, where the container keeps reconnecting it.

Run again after the phone reboots (TCP mode is lost) or changes IP address.
The phone and the computer must share a network. See docs/docker.md.
#>
[CmdletBinding()]
param(
    # USB serial; optional when exactly one USB device is attached.
    [string]$Serial,
    [ValidateRange(1024, 65535)][int]$Port = 5555
)

$ErrorActionPreference = 'Stop'
if (-not (Get-Command adb -ErrorAction SilentlyContinue)) {
    throw 'Host adb not found on PATH. Install Android platform-tools.'
}

# The appium container of whichever stack is running (dev container or compose.yaml).
$container = @(docker ps --filter 'label=com.docker.compose.service=appium' --format '{{.Names}}')
if ($container.Count -ne 1 -or -not $container[0]) {
    throw "Expected exactly one running appium container, found: $($container -join ', ')"
}
$container = $container[0]

if (-not $Serial) {
    # USB serials have no colon; network targets are host:port.
    $usb = @(adb devices | Select-Object -Skip 1 | ForEach-Object {
        $fields = $_ -split '\s+'
        if ($fields.Count -ge 2 -and $fields[1] -eq 'device' -and $fields[0] -notmatch ':') { $fields[0] }
    })
    if ($usb.Count -ne 1) {
        throw "Expected exactly one authorized USB device on the host, found $($usb.Count). Pass -Serial."
    }
    $Serial = $usb[0]
}

$address = adb -s $Serial shell ip -f inet addr show wlan0 |
    Select-String -Pattern 'inet (\d+\.\d+\.\d+\.\d+)/' |
    ForEach-Object { $_.Matches[0].Groups[1].Value } |
    Select-Object -First 1
if (-not $address) { throw "No Wi-Fi IPv4 address on $Serial. Connect the phone to Wi-Fi." }
$target = "${address}:$Port"

Write-Host "Switching $Serial to adb over TCP ($target)."
adb -s $Serial tcpip $Port | Out-Host
if ($LASTEXITCODE -ne 0) { throw "adb tcpip failed for $Serial." }
Start-Sleep -Seconds 3

# Replace any earlier target for this serial, keep other devices' targets.
$file = '/home/node/.android/connect-targets'
$script = "touch $file && grep -v ' $Serial`$' $file > $file.tmp; echo '$target $Serial' >> $file.tmp && mv $file.tmp $file"
docker exec $container sh -c $script
if ($LASTEXITCODE -ne 0) { throw "Could not record $target in $container." }

docker exec $container adb connect $target | Out-Host
Start-Sleep -Seconds 2
$state = docker exec $container adb devices |
    Where-Object { $_ -like "$target`t*" } |
    ForEach-Object { ($_ -split '\s+')[1] }

switch ($state) {
    'device' { Write-Host "Connected: $target is available in the console." }
    'unauthorized' {
        Write-Host "On the phone, allow USB debugging for this computer (tick 'Always allow')."
        Write-Host 'The console lists the device after authorization; no rerun needed.'
    }
    default {
        Write-Warning "State of ${target}: '$state'. The container keeps retrying; check Wi-Fi and firewall."
    }
}

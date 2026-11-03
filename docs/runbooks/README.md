# Runbooks

One page for each alert ok3d sends: what it means, what to check, in order, and when it clears. Every alert links to its page.

| Alert | Severity | What it means |
|---|---|---|
| [DeviceDown](DeviceDown.md) | critical | A device in `devices.yaml` hasn't answered ping for 2 minutes. |
| [DeviceCheckFailing](DeviceCheckFailing.md) | warning | A device answers ping, but one of its other checks (http, https, or tcp:<port>) has failed for 5 minutes. |
| [DeviceFlapping](DeviceFlapping.md) | warning | A device dropped off and came back at least twice in 15 minutes. |
| [DeviceMetricsDown](DeviceMetricsDown.md) | warning | Prometheus hasn't been able to read a device's metrics port (from `metrics` in `devices.yaml`) for 5 minutes. |
| [DeviceCertificateExpiring](DeviceCertificateExpiring.md) | warning | A device's HTTPS certificate runs out in less than two weeks. |
| [UniFiControllerUnreachable](UniFiControllerUnreachable.md) | warning | unpoller hasn't been able to read your UniFi controller for 10 minutes, so UniFi's graphs and alerts have stopped. |
| [UniFiDeviceBusy](UniFiDeviceBusy.md) | warning | A UniFi device's processor has been above 90% for 15 minutes. |
| [UniFiDeviceMemoryFull](UniFiDeviceMemoryFull.md) | warning | A UniFi device's memory has been above 90% for 15 minutes. |
| [HostDiskFillingUp](HostDiskFillingUp.md) | warning | A computer's disk is under 20% free and, at the pace of the last 6 hours, will be full within a day. |
| [HostDiskAlmostFull](HostDiskAlmostFull.md) | critical | A computer's disk has less than 5% free. |
| [HostMemoryLow](HostMemoryLow.md) | warning | A computer has had less than 5% of its memory free for 15 minutes. |
| [HostRaidDegraded](HostRaidDegraded.md) | critical | A computer's software RAID is missing a disk. |

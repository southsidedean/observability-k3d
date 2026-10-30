# UniFiControllerUnreachable

**Severity:** warning

unpoller hasn't been able to read your UniFi controller for 10 minutes, so UniFi's graphs and alerts have stopped. Your network may be fine.

## What to check

1. Is the controller up? Open its page (`unifi.url` in `settings.yaml`).
2. Is the API key still valid? A key is removed with its admin, or by hand. Make a new one and put it in `.env` (`UNIFI_API_KEY`), then `./ok3d apply`.
3. unpoller's log says why: `kubectl --context k3d-ok3d -n monitoring logs deploy/unpoller`.
4. If the controller's certificate changed and `unifi.verifyTls` is true, that's the cause.

## When it clears

It clears on its own when unpoller reads the controller again.

To keep it quiet while you work on it, add a [maintenance window](../alerts.md#maintenance-windows-keeping-alerts-quiet-while-you-work) on the Dashboard's Maintenance page, or with `./ok3d maintenance` on the server.

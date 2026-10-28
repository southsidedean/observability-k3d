"""The Dashboard: where you set ok3d up and change it, from a web page.

It runs in a container on the server, outside the cluster, so it keeps working when the
cluster is down. It can't run anything on the server itself: it leaves requests for the
helper (ok3d.helper) and reads the helper's answers. Like the helper, it uses only Python's
standard library, so its image has nothing to keep patched beyond Python.

    python -m ok3d.dashboard --state /state --helper /helper --cert ... --key ...

docs/dashboard-under-the-hood.md has the whole story.
"""

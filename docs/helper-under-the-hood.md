# The helper under the hood

How a click on the Dashboard's **Check** or **Apply** becomes `./ok3d check` or `./ok3d apply`
on the server. The Dashboard arrives later in 0.5; the helper comes first, because the
Dashboard depends on it. This page describes the code as it is, in `src/ok3d/helper.py`.

## Why there's a helper

The Dashboard runs in a container. To make the cluster, it would need Docker, and access to
Docker is as good as full control of the server. So the Dashboard gets no Docker and can't
run anything itself. It leaves a request in a file instead, and the helper, a small service
running on the server as you, carries it out.

The helper assumes someone may have taken over the Dashboard's container. The most they can
do through it is ask for `./ok3d check` or `./ok3d apply`, which you could run yourself.

## The pieces

| Piece | Where | What it does |
|---|---|---|
| The outbox | `<data root>/dashboard/outbox/` | The Dashboard writes its request here, as `request` |
| The helper's folder | `<data root>/helper/` | Only the helper writes here; the Dashboard can read it |
| `src/ok3d/helper.py` | the ok3d checkout | The helper itself: standard library only, run with the server's own Python |
| `deploy/ok3d-helper.service` | `~/.config/systemd/user/` | Runs the helper as a systemd user service, as you |

The helper makes both folders when it starts, readable only by you.

## A request, from click to answer

1. You press **Check** or **Apply**. The Dashboard writes `dashboard/outbox/request`:

   ```ini
   id=3f9a0c51d2e8b746
   action=check
   ```

   The id is a random number the page makes, so it knows which answer is to its own request.
2. Every 3 seconds, the helper renames that file into its own folder, as `helper/request`. A
   rename moves whatever is there: a link moves as a link, never what it points to. From then
   on, the helper opens nothing the Dashboard can reach.
3. It checks what arrived, and refuses it without running anything unless all of these hold:
   - It's a plain file, not a link, a folder, or a pipe, and not a hard link to another file.
   - It's at most 4 KB.
   - It was written in the last 5 minutes (or up to a minute ahead, for a clock that's off).
   - It's plain ASCII text, with each line ending in a newline.
   - It has exactly two lines, `id` and `action`, each once, and nothing else.
   - The id is 16 to 64 lowercase hex digits.
   - The action is `check` or `apply`, exactly.
   - The id isn't one of the last 100 the helper carried out, so a request can't be replayed.

   Then it removes what arrived, whatever it was.
4. It writes `helper/result` saying `state=running`, then runs `./ok3d check` or `./ok3d apply`
   in the ok3d checkout, with no input. A check may take 5 minutes and an apply an hour;
   after that, the helper stops it and everything it started.
5. It writes its answer to `helper/result`: a few lines, a blank line, then the last 200
   lines `ok3d` printed:

   ```ini
   id=3f9a0c51d2e8b746
   action=check
   state=finished
   exit=0
   finished=2026-10-28T18:05:12Z

   PASS  the settings in /home/you/ok3d/settings.yaml
   ...
   ```

   A refused request gets `state=refused` and a `reason`, from a fixed list. The answer never
   repeats anything the request said, not even its id.
6. The page reads `helper/result` every few seconds, and shows it when the id matches.

## What the helper writes

Everything stays in `<data root>/helper/`, readable only by you. Each file is written to a
temporary file first and renamed into place, so the page never reads half of one.

| File | What's in it |
|---|---|
| `request` | What it took from the outbox, only while it checks it |
| `result` | Its answer to the last request (above) |
| `output` | Everything `ok3d` printed for the last request |
| `seen` | The ids of the last 100 requests, so none runs twice |
| `lock` | Held while the helper runs, so a second one on the same data root won't start |

## Running it

The installer sets the service up later in 0.5. Until then, from the ok3d checkout:

```sh
python3 -I src/ok3d/helper.py once --ok3d-dir . --data-root /srv/ok3d    # handle one request
python3 -I src/ok3d/helper.py watch --ok3d-dir . --data-root /srv/ok3d   # keep watching
```

As a service, it logs one line for each request: `journalctl --user -u ok3d-helper -f`.

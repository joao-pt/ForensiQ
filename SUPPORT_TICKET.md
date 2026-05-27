# GitHub Support — Orphaned PR refs after history rewrite

> **STATUS: RESOLVIDO** (GitHub Support, 2026-05-27). Os `refs/pull/1/head`
> e `refs/pull/2/head` foram removidos do repositório `joao-pt/ForensiQ`
> e a contributor widget passou a reflectir apenas `joao-pt`.
>
> Este ficheiro fica como **registo histórico** do incident — descreve o
> problema (history rewrite com `git filter-repo` para remover
> `Co-Authored-By: …@anthropic.com`, force-push, e widget de contributors
> que continuava a mostrar o utilizador removido) e a request submetida
> ao GitHub Support. Útil para referência futura caso seja necessária
> outra limpeza semelhante.

---

**Where to submit:** https://support.github.com → "Contact us" → category **Repository** → subcategory **Other**

**Subject (copy this into the subject field):**

```
Reset contributor graph + remove orphaned refs/pull/* after history rewrite
```

**Description (copy everything below this line into the message body):**

---

## Summary

I performed a `git filter-repo` history rewrite followed by `git push --force` on the
`main` branch of my repository **joao-pt/ForensiQ** to remove `Co-Authored-By` trailers
(specifically the `noreply@anthropic.com` co-author) from past commits, for academic
attribution reasons.

After the force-push, the live `main` branch is fully clean, but the **Contributors
widget on the repository home page still lists the removed co-author as a contributor**.

I have already tried the following on my own without success:

- Force-push of the rewritten history (current `main` HEAD: `99b60ac91c2a9f9aa46b26d3d55c33d8ebff7f9f`).
- Blocked the user account at the personal level (Settings → Blocked users).
- Toggled the repository visibility (Public → Private → Public).
- Verified in incognito mode and on a different machine — the widget still shows the
  removed user.

## Root cause I identified

The orphaned PR refs still pin pre-rewrite commits that contain the
`Co-Authored-By` trailer in their commit message body:

| Ref | SHA | Contains `Co-Authored-By: ...@anthropic.com`? |
|-----|-----|----------------------------------------------|
| `refs/pull/1/head` | `8736fc829c97fe38562a354e1ef57d47892c0f9f` | Yes (and ancestors of this ref also contain it) |
| `refs/pull/2/head` | `5fd773ed0e5d30d204e8c670f07b1b192051e8d3` | Yes |

These refs are hidden, so they cannot be deleted by the repo admin:

```
$ git push origin --delete refs/pull/1/head
! [remote rejected] refs/pull/1/head (deny updating a hidden ref)
```

Both PRs (#1 and #2) are already **closed and merged**, and their entire content is
already integrated into the rewritten `main` history. There is no information loss in
removing the orphaned heads.

## Evidence that `main` itself is clean

```
$ curl -s "https://api.github.com/repos/joao-pt/ForensiQ/contributors"
[
  { "login": "joao-pt", "contributions": 120 }
]
```

`/repos/.../contributors`, `/repos/.../collaborators`, `/repos/.../assignees`,
`/repos/.../commits?author=claude` all return only `joao-pt` (or empty in the case of
`author=claude`).

## Request

Please either:

1. **Delete `refs/pull/1/head` and `refs/pull/2/head`** from `joao-pt/ForensiQ`, **or**
2. **Force a re-computation of the contributor statistics** for `joao-pt/ForensiQ` so the
   widget reflects only the current state of `main`.

Option 1 is preferred — it eliminates the orphaned data entirely.

## Additional context

This is a personal academic repository (no organization). I am the sole contributor.
The PRs were self-merged by me only.

Thank you!

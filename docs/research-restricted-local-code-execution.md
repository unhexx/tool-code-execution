# Research result

**Status: Partial**

A loopback Python `code_execution` tool that must refuse network and filesystem access cannot treat an in-process AST allowlist as the security boundary. RestrictedPython and production write-ups both treat language rewriting as a filter that misses runtime reflection, and they put the real stop in a separate process with a wall-clock kill the guest cannot clear. For this repository’s threat (model-written snippets on one machine, stdlib HTTP on `127.0.0.1`, optional Docker), the matching shape is a fresh worker process per call, killed by the parent, with network and filesystem closed by the kernel. A long-lived container around an in-process `exec` does not give that. gVisor or a Firecracker microVM is the step up when the code is treated as hostile; both are heavier than this tree’s current server.

### What the shipped tool is doing

The server parses source, walks an AST allowlist, then `exec`s in the same interpreter with a stripped `__builtins__`. `timeout_sec` is advertised and not applied. Allowed import roots include `io`, `operator`, `functools`, and `string`. Compose can drop capabilities, make the root read-only, cap memory and pids, and set `TOOL_OFFLINE=1`, but that flag is unread and the sandbox is still one process for every request. Those facts are from this tree (`src/code_execution/server.py`, `src/tool_http.py`, `docker-compose.yml`), not from the sources below.

### Language filters are not an environment boundary

RestrictedPython compiles a subset of Python and rewrites attribute access written in the restricted source into guard calls. It does not restrict the `globals` and `__builtins__` passed to `exec`. Guards never see lookups performed inside a callable: `operator.attrgetter('__globals__')` succeeds because `attrgetter` calls `getattr` in C. The project ships no `__import__`. `safe_builtins` omits it, so imports fail with `ImportError: __import__ not found` until the host supplies a hook. A denylist of modules does not work; only an allowlist does. `os`, `subprocess`, `sys`, `shutil`, `operator`, `functools`, `ctypes`, `inspect`, `gc`, `importlib`, `pickle`, and `string` are each enough to leave restricted code. `string.Formatter` walks attributes without the guard, and a plain `import string` bypasses the safer wrapper. Allowing `import x` exposes all of `x`. Prefer injecting specific callables over handing over a module. [S1]

The same hole shows up with a hand-rolled AST walk. `"{0.__class__}".format(obj)` and `format_map` perform attribute access from a runtime string, which the AST never sees. Handing over a module object is worse: a “helpful” `urllib.parse` can reach `sys` and then native execution. The fix described there is to expose individual callables, not modules, and to ban reflection methods by name. [S2]

sandtrap 0.4.4 is the closest small library to this tree: AST rewriting, import and attribute policy, and three levels (`none`, `process`, `kernel`). The default is in-process and shares the host address space. The project states it is a walled garden for cooperative agent scripts, not adversarial input. Kernel mode (seccomp plus Landlock or Seatbelt) is defense in depth for a stray network call or a walk outside a root. It is not an escape boundary: the Python layer is not adversarial-safe, and worker IPC uses pickle. If the kernel pieces are missing, `isolation="kernel"` raises rather than running unprotected, unless degradation is explicitly allowed. [S3]

### Time and resource limits have to be outside the guest

A static allowlist says nothing about `while True` or a huge allocation. One production design runs each snippet in a fresh subprocess, drops to an unprivileged uid before `exec`, sets `RLIMIT_CPU`, `RLIMIT_AS`, `RLIMIT_NOFILE`, and `RLIMIT_NPROC`, and arms `SIGALRM` inside the worker. The parent also passes `timeout` to `subprocess.run`, because an in-process alarm can be defeated. `RLIMIT_FSIZE = 0` is a trap: it can kill the worker on its own stderr. Seccomp and Landlock sit behind the Python layers and are allowed to no-op; the uid drop and the parent timeout still stand. [S2]

The standard library’s contract matches that outer kill. `subprocess.run(..., timeout=...)` waits, and if the timeout expires the child is killed and `TimeoutExpired` is raised after the child has terminated. Process creation itself is not interruptible on many platforms, so the exception is not guaranteed until creation has finished. [S4]

### Isolation classes that fit a local tool

Three classes show up repeatedly, and they answer different questions.

Linux namespaces, seccomp, and Landlock shrink what a process can touch, but the workload still talks to the host kernel. gVisor’s security introduction states that the workload is then one syscall away from host compromise, and that a generic filter ends up allowing most of the kernel surface. [S5]

bubblewrap builds an empty mount namespace (root on a tmpfs cleaned up when the last process exits) and can add user, IPC, PID, UTS, and network namespaces plus a caller-supplied seccomp filter. A new network namespace does not see the host network; it has only loopback. bubblewrap is not a policy. Protection is exactly the arguments the caller passes, and anything bind-mounted in (a D-Bus socket is the documented example) can be an escape. It sets `PR_SET_NO_NEW_PRIVS`. It does not, by itself, apply cgroup memory or CPU caps. [S6]

gVisor is an application kernel (the Sentry), written in Go, running in userspace. It intercepts the workload’s syscalls and handles them itself; it does not pass those syscalls through to the host. The OCI runtime is `runsc`. With `--rootless --network=none` it can start without root when no network stack is required. It does not stop an exploit that stays inside whatever the sandbox was configured to see, and it does not stop CPU side channels. Breaking out requires exploiting the Sentry and the host kernel, which share no code. [S5]

E2B Runtime (Apache-2.0, Go) gives each sandbox its own Firecracker microVM, cgroup, and network namespace, plus a per-sandbox nftables egress firewall. Templates are snapshotted VMs; create restores a snapshot rather than booting cold. The Embed package runs that stack on one Linux host with KVM via Docker Compose. That is a different operations load from a stdlib HTTP server. [S7]

### Local products aimed at model-written Python

kern-sandbox runs each call in a fresh rootless container from an OCI image, with no network, memory and pid caps, and a deadline applied from outside, then discards the container. A bare `Sandbox()` uses `python:3.12-slim`, a 30 second deadline that cannot be disabled, no host mounts, seccomp, and dropped capabilities. It distinguishes timeout, OOM, and a normal Python exception in the result. The project says this is not a boundary for deliberately hostile code; use a microVM or gVisor for that. Cgroup caps apply only when the host delegates a cgroup; `require_limits=True` refuses to start rather than run uncapped. It describes bubblewrap and nsjail as the building blocks underneath, without images, cgroup caps, or a labelled fault. [S8]

sandtrap’s process and kernel modes are the library-shaped version of the same split: crash isolation in a worker, optional Landlock or Seatbelt and seccomp, still not an adversarial boundary. [S3]

### What that implies for this repository

The gaps already visible in the tree line up with these sources, not with a missing product feature.

- An AST walk plus stripped builtins is the cheap first filter [S1][S2]. It does not stop `str.format`, and it does not stop modules the allowlist already names. RestrictedPython calls out `operator`, `functools`, and `string` specifically; this server allows all three, plus `io`. [S1]
- `timeout_sec` has to be a parent-side kill of another process [S2][S4]. There is no reliable equivalent inside the request thread that is running the snippet.
- A long-lived container with `cap_drop`, a read-only root, and pid/memory limits is a host backstop for the server process. It is not a per-snippet jail, and it does not implement the unread `TOOL_OFFLINE` flag. Per-call network denial in the products above is a namespace, seccomp, or container flag, not an environment variable the guest is trusted to honor [S6][S8].
- Sharing one interpreter across requests leaves state and a crashed C extension in the server. Both sandtrap and the subprocess design throw the worker away [S2][S3].
- Moving the whole tool to E2B Embed or `runsc` would match a hostile-code threat model and would replace the current process model [S5][S7]. kern-sandbox’s own security note draws that line: namespaces and seccomp for semi-trusted code, microVM or gVisor when the code is hostile [S8].

## Sources

- [S1] RestrictedPython 8.2 — Security considerations — https://restrictedpython.readthedocs.io/en/latest/usage/security_considerations.html
- [S2] Six Layers to Sandbox Untrusted Python — https://chs.us/2026/07/sandboxing-untrusted-python/
- [S3] sandtrap 0.4.4 — https://pypi.org/project/sandtrap/
- [S4] Python 3 docs — `subprocess.run` timeout — https://docs.python.org/3/library/subprocess.html#subprocess.run
- [S5] Introduction to gVisor security — https://gvisor.dev/docs/architecture_guide/intro/
- [S6] bubblewrap README — https://github.com/containers/bubblewrap/blob/main/README.md
- [S7] E2B Runtime README — https://github.com/e2b-dev/runtime
- [S8] kern-sandbox 0.2.48 — https://pypi.org/project/kern-sandbox/

## Coverage and uncertainty

- Claims above were checked by opening those eight pages in this pass. A second independent verifier was not run, so this report is Partial rather than double-verified.
- Vendor timing numbers on the kern-sandbox page (container startup versus `docker run`) were not reproduced and are not used above.
- Hosted-only comparisons (Daytona after its 2026 source closure, Modal’s default runtime, OpenAI Code Interpreter internals) were not opened as primary documents and are omitted.
- nsjail configuration examples from secondary blogs were not opened against the upstream manual and are omitted. kern-sandbox’s own page is the only place nsjail is mentioned here, and only as a building block it names [S8].
- gVisor’s page describes the mechanism. It does not give a compatibility matrix for CPython 3.12 stdlib imports, so this report does not claim that `runsc` runs this tool’s allowlisted modules unchanged [S5].

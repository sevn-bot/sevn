#include <libgen.h>
#include <limits.h>
#include <mach-o/dyld.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static int resolve_under(const char *macos_dir, const char *relative, char *out, size_t out_len) {
    char joined[PATH_MAX];
    int wrote = snprintf(joined, sizeof joined, "%s/%s", macos_dir, relative);
    if (wrote < 0 || (size_t)wrote >= sizeof joined) {
        fprintf(stderr, "sevn-host: path too long\n");
        return -1;
    }
    if (realpath(joined, out) == NULL || strlen(out) >= out_len) {
        perror(relative);
        return -1;
    }
    return 0;
}

int main(void) {
    char exe[PATH_MAX];
    uint32_t size = (uint32_t)sizeof exe;
    if (_NSGetExecutablePath(exe, &size) != 0) {
        fprintf(stderr, "sevn-host: executable path too long\n");
        return 1;
    }

    char resolved[PATH_MAX];
    if (realpath(exe, resolved) == NULL) {
        perror("sevn-host");
        return 1;
    }

    char dirbuf[PATH_MAX];
    snprintf(dirbuf, sizeof dirbuf, "%s", resolved);
    char *macos = dirname(dirbuf);

    char python[PATH_MAX];
    char site[PATH_MAX];
    char server[PATH_MAX];
    if (resolve_under(macos, "../Resources/python/bin/python3.13", python, sizeof python) != 0 ||
        resolve_under(macos, "../Resources/site", site, sizeof site) != 0 ||
        resolve_under(macos, "../Resources/server", server, sizeof server) != 0) {
        return 1;
    }

    char pythonpath[PATH_MAX * 3];
    const char *existing = getenv("PYTHONPATH");
    int wrote;
    if (existing != NULL && existing[0] != '\0') {
        wrote = snprintf(pythonpath, sizeof pythonpath, "%s:%s:%s", site, server, existing);
    } else {
        wrote = snprintf(pythonpath, sizeof pythonpath, "%s:%s", site, server);
    }
    if (wrote < 0 || (size_t)wrote >= sizeof pythonpath) {
        fprintf(stderr, "sevn-host: PYTHONPATH too long\n");
        return 1;
    }
    if (setenv("PYTHONPATH", pythonpath, 1) != 0 || setenv("PYTHONNOUSERSITE", "1", 1) != 0 ||
        setenv("PYTHONDONTWRITEBYTECODE", "1", 1) != 0) {
        perror("sevn-host");
        return 1;
    }

    execl(python, python, "-m", "sevn_spike_server", (char *)NULL);
    perror("sevn-host");
    return 1;
}

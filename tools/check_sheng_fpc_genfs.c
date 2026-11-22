/* Inspect libsepol's actual prefix lookup in the compiled boot policy. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sepol/sepol.h>
#include <sepol/policydb/services.h>

int main(int argc, char **argv) {
    if (argc != 2) return 2;
    FILE *policy = fopen(argv[1], "rb");
    if (!policy) return 2;
    int loaded = sepol_set_policydb_from_file(policy);
    fclose(policy);
    if (loaded) return 2;
    sepol_security_class_t file_class;
    if (sepol_string_to_security_class("file", &file_class)) return 2;
    const struct { const char *path; const char *context; } checks[] = {
        {"/devices/platform/soc/soc:fingerprint_fpc/wakeup_enable", "u:object_r:sysfs_fingerprint_sheng:s0"},
        {"/devices/platform/soc/soc:fingerprint_fpc/irq", "u:object_r:sysfs_fingerprint_sheng:s0"},
        {"/devices/platform/soc/soc:fingerprint_fpc/wakeup/wakeup2/name", "u:object_r:sysfs_wakeup:s0"},
        {"/devices/platform/soc/soc:fingerprint_fpc/wakeup/wakeup3/active_count", "u:object_r:sysfs_wakeup:s0"},
    };
    int failed = 0;
    for (size_t i = 0; i < sizeof(checks) / sizeof(checks[0]); ++i) {
        sepol_security_id_t sid;
        sepol_security_context_t context = NULL;
        size_t length;
        if (sepol_genfs_sid("sysfs", checks[i].path, file_class, &sid) ||
            sepol_sid_to_context(sid, &context, &length)) return 2;
        printf("%s %s\n", checks[i].path, context);
        if (strcmp(context, checks[i].context)) failed = 1;
        free(context);
    }
    return failed;
}

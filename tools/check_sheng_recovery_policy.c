/* Verify firmware labels and access decisions in a compiled Recovery policy. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sepol/sepol.h>
#include <sepol/policydb/services.h>

static sepol_security_class_t file_class;

static int check_path(const char *path, const char *expected,
                      sepol_security_id_t *sid) {
    sepol_security_context_t context = NULL;
    size_t length;
    if (sepol_genfs_sid("sysfs", path, file_class, sid) ||
        sepol_sid_to_context(*sid, &context, &length)) return 2;
    printf("%s %s\n", path, context);
    int result = strcmp(context, expected) != 0;
    free(context);
    return result;
}

static int check_access(const char *source, sepol_security_id_t target,
                        const char *permission, int expected) {
    sepol_security_id_t source_sid;
    sepol_access_vector_t requested;
    struct sepol_av_decision decision;
    if (sepol_context_to_sid(source, strlen(source) + 1, &source_sid) ||
        sepol_string_to_av_perm(file_class, permission, &requested) ||
        sepol_compute_av(source_sid, target, file_class, requested, &decision)) return 2;
    int allowed = (decision.allowed & requested) == requested;
    printf("%s file:%s allowed=%d expected=%d\n", source, permission, allowed, expected);
    return allowed != expected;
}

int main(int argc, char **argv) {
    if (argc != 2) return 2;
    FILE *policy = fopen(argv[1], "rb");
    if (!policy) return 2;
    int loaded = sepol_set_policydb_from_file(policy);
    fclose(policy);
    if (loaded || sepol_string_to_security_class("file", &file_class)) return 2;

    sepol_security_id_t firmware, sibling;
    if (check_path("/module/firmware_class/parameters/path",
                   "u:object_r:vendor_sysfs_sheng_firmware_path:s0", &firmware) ||
        check_path("/module/firmware_class/parameters/unrelated",
                   "u:object_r:sysfs:s0", &sibling)) return 1;
    if (check_access("u:r:init:s0", firmware, "open", 1) ||
        check_access("u:r:init:s0", firmware, "write", 1) ||
        check_access("u:r:init:s0", sibling, "write", 0) ||
        check_access("u:r:recovery:s0", firmware, "open", 1) ||
        check_access("u:r:recovery:s0", firmware, "read", 1) ||
        check_access("u:r:recovery:s0", firmware, "getattr", 1)) return 1;
    return 0;
}

// SPDX-License-Identifier: GPL-2.0-only
/* Read one regular file from a local image, avoiding a full tree extraction. */
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <unistd.h>
#include "erofs/config.h"
#include "erofs/internal.h"

int main(int argc, char **argv)
{
    struct erofs_sb_info sbi = {0};
    struct erofs_inode inode = {.sbi = &sbi};
    char *buffer = NULL;
    int result = 1, fd = -1;
    if (argc != 4) {
        fprintf(stderr, "usage: erofs-read-file IMAGE /PATH NEW_OUTPUT\n");
        return 2;
    }
    erofs_init_configure();
    cfg.c_dbg_lvl = 0;
    if (erofs_dev_open(&sbi, argv[1], O_RDONLY))
        return 1;
    if (erofs_read_superblock(&sbi) || erofs_ilookup(argv[2], &inode))
        goto done;
    if (!S_ISREG(inode.i_mode) || inode.i_size > 32U * 1024U * 1024U)
        goto done;
    buffer = malloc(inode.i_size ? inode.i_size : 1);
    if (!buffer || erofs_pread(&inode, buffer, inode.i_size, 0))
        goto done;
    fd = open(argv[3], O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0600);
    if (fd < 0)
        goto done;
    for (size_t offset = 0; offset < inode.i_size;) {
        ssize_t count = write(fd, buffer + offset, inode.i_size - offset);
        if (count < 0 && errno == EINTR)
            continue;
        if (count <= 0)
            goto done;
        offset += count;
    }
    result = 0;
done:
    if (fd >= 0)
        close(fd);
    free(buffer);
    erofs_dev_close(&sbi);
    if (result)
        fprintf(stderr, "Failed reading regular image file %s\n", argv[2]);
    return result;
}

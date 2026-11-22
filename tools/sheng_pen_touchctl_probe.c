// SPDX-License-Identifier: Apache-2.0
// Temporary fixed pen operations using the verified supplied 520-byte touch ABI.
#define _GNU_SOURCE
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/ioctl.h>
#include <errno.h>
#include <stddef.h>
#include <sys/socket.h>
#include <sys/un.h>
struct command { uint8_t panel, operation; uint16_t mode, count, reserved; int32_t data[128]; };
_Static_assert(sizeof(struct command)==520,"TouchFeature v2");
// The supplied HAL first informs THP of mode 20, then uses the driver fallback.
// Bypassing THP leaves its pen-type selector unchanged even when ioctl succeeds.
static int notify_pen_type(int value) {
    int fd=socket(AF_UNIX,SOCK_STREAM|SOCK_CLOEXEC,0);
    if(fd<0) return -1;
    struct timeval timeout={1,0};
    if(setsockopt(fd,SOL_SOCKET,SO_RCVTIMEO,&timeout,sizeof(timeout))<0 ||
       setsockopt(fd,SOL_SOCKET,SO_SNDTIMEO,&timeout,sizeof(timeout))<0) {close(fd);return -1;}
    struct sockaddr_un address={.sun_family=AF_UNIX};
    const char name[]="thp_socket";memcpy(address.sun_path+1,name,sizeof(name)-1);
    if(connect(fd,(struct sockaddr*)&address,offsetof(struct sockaddr_un,sun_path)+sizeof(name))<0) {close(fd);return -1;}
    struct ucred peer; socklen_t peer_size=sizeof(peer);
    if(getsockopt(fd,SOL_SOCKET,SO_PEERCRED,&peer,&peer_size)<0 || peer_size!=sizeof(peer) || peer.uid!=1000) {close(fd);return -1;}
    struct command c={.mode=20,.count=1,.data={value}};
    size_t done=0;
    while(done<sizeof(c)) {
        ssize_t n=send(fd,(char*)&c+done,sizeof(c)-done,MSG_NOSIGNAL);
        if(n<0 && errno==EINTR) continue;
        if(n<=0) {close(fd);return -1;}done+=(size_t)n;
    }
    done=0;
    while(done<sizeof(c)) {
        ssize_t n=recv(fd,(char*)&c+done,sizeof(c)-done,0);
        if(n<0 && errno==EINTR) continue;
        if(n<=0) {close(fd);return -1;}done+=(size_t)n;
    }
    close(fd);
    printf("pen_thp mode=20 value=%d panel=%u operation=%u count=%u\n",value,c.panel,c.operation,c.count);
    return c.panel==0 && c.operation==0 && c.mode==20 && (c.count==0 || c.count==65535) ? 0:-1;
}
int main(int argc,char **argv) {
    if(argc!=3) return 2;
    char *end; long value=strtol(argv[2],&end,10);
    if(!*argv[2]||*end) return 2;
    unsigned mode;
    if(!strcmp(argv[1],"connect") && (value==3||value==8)) {mode=20;value|=16;}
    else if(!strcmp(argv[1],"disconnect") && (value==3||value==8)) mode=20;
    else if(!strcmp(argv[1],"active") && (value==0||value==1)) mode=29;
    else if(!strcmp(argv[1],"ready") && (value==0||value==1)) mode=37;
    else if(!strcmp(argv[1],"id") && value>=0 && value<=65535 && ((value&255)==1||(value&255)==3)) mode=22;
    else if(!strcmp(argv[1],"frequency-ack") && value==49) mode=22;
    else return 2;
    char state[16]={0}; int panel=open("/sys/class/drm/card0-DSI-1/dpms",O_RDONLY|O_CLOEXEC);
    if(panel<0) return 3;
    ssize_t n=read(panel,state,sizeof(state)-1);close(panel);
    if(n<2 || strncmp(state,"On",2)) {puts("Deferred: panel is off");return 3;}
    if(mode==20 && notify_pen_type((int)value)<0) {puts("Pen type THP notification failed");return 1;}
    int fd=open("/dev/xiaomi-touch",O_RDWR|O_CLOEXEC);
    if(fd<0) {perror("touch open");return 1;}
    if(ioctl(fd,0x5403,NULL)<0) {perror("select panel");close(fd);return 1;}
    struct command c={.mode=mode,.count=1,.data={(int32_t)value}};
    int result=ioctl(fd,0xc2085400,&c),error=errno;close(fd);
    printf("pen_ioctl mode=%u value=%ld result=%d errno=%d count=%u data0=%d\n",mode,value,result,result<0?error:0,c.count,c.data[0]);
    return result<0?1:0;
}

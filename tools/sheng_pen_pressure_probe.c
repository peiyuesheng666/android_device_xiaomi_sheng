// SPDX-License-Identifier: Apache-2.0
// Bounded diagnostic: real Focus Pen Pro report 5 -> supplied THP operation 7.
// Never grabs HID, synthesizes input, changes controller modes or writes firmware.
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <linux/hidraw.h>
#include <linux/input.h>
#include <poll.h>
#include <signal.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <time.h>
#include <unistd.h>

struct command { uint8_t panel, operation; uint16_t mode, count, reserved; int32_t data[128]; };
_Static_assert(sizeof(struct command)==520,"stock common_data ABI");
static volatile sig_atomic_t stopping;
static void stop(int sig) { (void)sig; stopping=1; }
static double now(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC,&t); return t.tv_sec+t.tv_nsec/1e9; }
static int panel_on(void) {
    char buf[16]={0}; int fd=open("/sys/class/drm/card0-DSI-1/dpms",O_RDONLY|O_CLOEXEC);
    if(fd<0) return 0;
    ssize_t n=read(fd,buf,sizeof(buf)-1);close(fd);
    return n>0 && (!strcmp(buf,"On\n")||!strcmp(buf,"On"));
}
static int pen_identity(int fd) {
    struct hidraw_devinfo info={0}; char name[128]={0},uniq[128]={0};
    if(ioctl(fd,HIDIOCGRAWINFO,&info)<0 || info.bustype!=5 || info.vendor!=34 || info.product!=20609) return 0;
    if(ioctl(fd,HIDIOCGRAWNAME(sizeof(name)),name)<0 || strcmp(name,"Xiaomi Focus Pen Pro")) return 0;
    if(ioctl(fd,HIDIOCGRAWUNIQ(sizeof(uniq)),uniq)<0 || strcasecmp(uniq,"28:ce:15:31:70:0e")) return 0;
    return 1;
}
static int connect_thp(void) {
    int fd=socket(AF_UNIX,SOCK_STREAM|SOCK_CLOEXEC,0);
    if(fd<0) return -1;
    struct timeval t={2,0};
    if(setsockopt(fd,SOL_SOCKET,SO_RCVTIMEO,&t,sizeof(t))<0 ||
       setsockopt(fd,SOL_SOCKET,SO_SNDTIMEO,&t,sizeof(t))<0) {close(fd);return -1;}
    struct sockaddr_un addr={.sun_family=AF_UNIX};
    const char name[]="thp_socket"; memcpy(addr.sun_path+1,name,sizeof(name)-1);
    if(connect(fd,(struct sockaddr*)&addr,offsetof(struct sockaddr_un,sun_path)+sizeof(name))<0) {close(fd);return -1;}
    struct ucred peer; socklen_t size=sizeof(peer);
    if(getsockopt(fd,SOL_SOCKET,SO_PEERCRED,&peer,&size)<0 || size!=sizeof(peer) || peer.uid!=1000) {close(fd);return -1;}
    printf("THP peer_uid=%u pid=%d\n",peer.uid,peer.pid);return fd;
}
static int forward(int fd,const unsigned char report[15]) {
    struct command c={.operation=7,.mode=1088,.count=15};
    for(int i=0;i<15;++i) c.data[i]=report[i];
    size_t done=0;
    while(done<sizeof(c)) {
        ssize_t n=send(fd,(char*)&c+done,sizeof(c)-done,MSG_NOSIGNAL);
        if(n<0 && errno==EINTR && !stopping) continue;
        if(n<=0) return -1;
        done+=(size_t)n;
    }
    done=0;
    while(done<sizeof(c)) {
        ssize_t n=recv(fd,(char*)&c+done,sizeof(c)-done,0);
        if(n<0 && errno==EINTR && !stopping) continue;
        if(n<=0) return -1;
        done+=(size_t)n;
    }
    printf("ACK panel=%u op=%u mode=%u count=%u data0=%d\n",c.panel,c.operation,c.mode,c.count,c.data[0]);
    return c.panel==0 && c.operation==7 && c.mode==1088 && c.count==0 ? 0:-1;
}
static int input_open(const char *path,const char *expected) {
    int fd=open(path,O_RDONLY|O_NONBLOCK|O_CLOEXEC);char name[128]={0};
    if(fd<0) return -1;
    if(ioctl(fd,EVIOCGNAME(sizeof(name)),name)<0 || strcmp(name,expected)) {close(fd);return -1;}
    return fd;
}
int main(int argc,char **argv) {
    if(argc!=2 || (strcmp(argv[1],"observe") && strcmp(argv[1],"forward"))) return 2;
    int forwarding=!strcmp(argv[1],"forward");
    setvbuf(stdout,NULL,_IOLBF,0);signal(SIGPIPE,SIG_IGN);
    signal(SIGTERM,stop);signal(SIGINT,stop);signal(SIGHUP,stop);
    int pen=open("/dev/hidraw4",O_RDONLY|O_NONBLOCK|O_CLOEXEC);
    if(pen<0 || !pen_identity(pen)) {puts("Exact live Pro HID identity unavailable");if(pen>=0)close(pen);return 3;}
    struct pollfd fds[3]={{pen,POLLIN,0},{input_open("/dev/input/event7","NVTCapacitivePenM80p"),POLLIN,0},
                            {input_open("/dev/input/event8","NVTCapacitivePenP81c"),POLLIN,0}};
    // Device names are checked against the live controller before accepting any event.
    if(fds[1].fd<0 || fds[2].fd<0) {puts("Expected NVT pen endpoint unavailable");for(int i=0;i<3;++i)if(fds[i].fd>=0)close(fds[i].fd);return 3;}
    int socket_fd=forwarding?connect_thp():-1;
    if(forwarding && socket_fd<0) {perror("THP connection");for(int i=0;i<3;++i)close(fds[i].fd);return 1;}
    unsigned reports=0,rejected=0,acks=0,events=0;int failed=0;
    double end=now()+600,active_end=end;
    printf("READY mode=%s real Pro HID / NVT recording; bounded 600s wait, 180s after first report\n",argv[1]);
    while(!stopping && now()<end && now()<active_end && reports<100000) {
        int n=poll(fds,3,200);
        if(n<0) {if(errno==EINTR)continue;failed=1;break;}
        for(int i=0;i<3;++i) if(fds[i].revents&(POLLERR|POLLHUP|POLLNVAL)) {failed=1;stopping=1;}
        if(stopping) break;
        if(fds[0].revents&POLLIN) {
            unsigned char buf[128];ssize_t got=read(pen,buf,sizeof(buf));
            if(got<0 && (errno==EINTR||errno==EAGAIN)) continue;
            if(got<=0) {failed=1;break;}
            if(got!=15 || buf[0]!=5) {++rejected;printf("REJECT length=%zd id=%u\n",got,buf[0]);continue;}
            if(!reports) active_end=now()+180;
            ++reports;
            printf("HID time=%.9f report=",now());for(int j=0;j<15;++j)printf("%02x",buf[j]);puts("");
            if(forwarding && panel_on()) {
                if(forward(socket_fd,buf)<0) {perror("THP exchange");failed=1;break;}++acks;
            }
        }
        for(int i=1;i<3;++i) if(fds[i].revents&POLLIN) {
            struct input_event ev[64];ssize_t got=read(fds[i].fd,ev,sizeof(ev));
            if(got<0 && (errno==EINTR||errno==EAGAIN)) continue;
            if(got<=0 || got%(ssize_t)sizeof(ev[0])) {failed=1;stopping=1;break;}
            for(size_t j=0;j<(size_t)got/sizeof(ev[0]);++j) {
                ++events;printf("NVT endpoint=%d time=%ld.%06ld type=%u code=%u value=%d\n",i,ev[j].time.tv_sec,ev[j].time.tv_usec,ev[j].type,ev[j].code,ev[j].value);
                if(ev[j].type==EV_SYN && ev[j].code==SYN_DROPPED) {failed=1;stopping=1;break;}
            }
        }
    }
    if(socket_fd>=0)close(socket_fd);
    for(int i=0;i<3;++i)close(fds[i].fd);
    printf("FINISHED reports=%u rejected=%u acknowledgements=%u nvt_events=%u failed=%d\n",reports,rejected,acks,events,failed);
    return failed?1:0;
}

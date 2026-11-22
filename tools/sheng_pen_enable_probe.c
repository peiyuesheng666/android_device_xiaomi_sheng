// SPDX-License-Identifier: Apache-2.0
// Temporary sheng trial: exact Pro HID identity, panel gating, fixed OEM mode 20.
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/types.h>
#include <poll.h>
#include <fcntl.h>
#include <unistd.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#include <time.h>
#include <linux/input.h>

struct command { uint8_t panel, operation; uint16_t mode, count, reserved; int32_t data[128]; };
_Static_assert(sizeof(struct command) == 520, "Stock touchfeature_v2 ABI");
static int text(const char *path, char *value, size_t size) {
    int fd = open(path, O_RDONLY | O_CLOEXEC);
    if (fd < 0) return -1;
    int n = read(fd, value, size-1); close(fd);
    if (n <= 0) return -1;
    value[n] = 0; return 0;
}
static int awake(void) {
    char value[32];
    return !text("/sys/class/drm/card0-DSI-1/dpms", value, sizeof(value)) && !strncmp(value,"On",2);
}
static int stylus(void) {
    char value[256]; int enabled = -1;
    if (!text("/proc/xm_htc_stylus_enable", value, sizeof(value))) sscanf(value,"stylus_enable: %d", &enabled);
    return enabled;
}
static int set_pro(int enabled) {
    int fd = socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
    if (fd < 0) return -1;
    struct timeval timeout = {1,0};
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
    setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout));
    struct sockaddr_un address = {.sun_family=AF_UNIX};
    memcpy(address.sun_path+1, "thp_socket", 10);
    if (connect(fd, (struct sockaddr*)&address, offsetof(struct sockaddr_un,sun_path)+11)) { close(fd); return -1; }
    struct ucred peer; socklen_t peer_size=sizeof(peer);
    if (getsockopt(fd,SOL_SOCKET,SO_PEERCRED,&peer,&peer_size) || peer.uid!=1000) { close(fd); return -1; }
    // ColorOS sheng helper: regular=19/3, P81c Pro=20/4. No other touch modes.
    struct command c = {.mode=20,.count=1,.data={enabled?20:4}};
    size_t sent=0, received=0;
    while (sent<sizeof(c)) { int n=send(fd,(char*)&c+sent,sizeof(c)-sent,MSG_NOSIGNAL); if(n<=0) {close(fd);return -1;} sent+=n; }
    while (received<sizeof(c)) { int n=recv(fd,(char*)&c+received,sizeof(c)-received,0); if(n<=0) {close(fd);return -1;} received+=n; }
    close(fd);
    printf("mode20 value=%d reply_mode=%u count=%u\n",enabled?20:4,c.mode,c.count);
    return c.panel==0 && c.operation==0 && c.mode==20 && c.count==0 ? 0:-1;
}
int main(void) {
    setvbuf(stdout,NULL,_IONBF,0);
    char path[128], value[2048]; int hid=-1;
    for(int i=0;i<32;i++) {
        snprintf(path,sizeof(path),"/sys/class/hidraw/hidraw%d/device/uevent",i);
        if(text(path,value,sizeof(value)) || !strstr(value,"HID_ID=0005:00000022:00005081") ||
           !strstr(value,"HID_UNIQ=28:ce:15:31:70:0e")) continue;
        snprintf(path,sizeof(path),"/dev/hidraw%d",i); hid=open(path,O_RDONLY|O_NONBLOCK|O_CLOEXEC); break;
    }
    if(hid<0) {puts("Actual bonded Focus Pen Pro HID missing");return 1;}
    puts("Waiting up to 600s for stable DSI panel On; no input grab");
    int stable=0;
    for(int i=0;i<600 && stable<2;i++) { stable=awake()?stable+1:0; sleep(1); }
    if(stable<2 || !awake() || stylus()!=0) {puts("Trial skipped: screen or baseline unknown");close(hid);return 1;}
    if(set_pro(1)) {puts("Enable transport failed; attempting restore");set_pro(0);close(hid);return 1;}
    printf("After enable stylus=%d; recording for up to 180s\n",stylus());
    int pen0=open("/dev/input/event7",O_RDONLY|O_NONBLOCK|O_CLOEXEC);
    int pen1=open("/dev/input/event8",O_RDONLY|O_NONBLOCK|O_CLOEXEC);
    struct pollfd fds[3]={{hid,POLLIN,0},{pen0,POLLIN,0},{pen1,POLLIN,0}};
    time_t deadline=time(NULL)+180;
    unsigned packets=0, pressure_packets=0, events[2]={0}, contact[2]={0}; int pmin=65535,pmax=0;
    while(time(NULL)<deadline && awake()) {
        if(poll(fds,3,200)<0) break;
        if(fds[0].revents&POLLIN) {
            uint8_t bytes[128]; int n;
            while((n=read(hid,bytes,sizeof(bytes)))>0) {
                if(packets++<15) {printf("HID %d:",n);for(int i=0;i<n;i++)printf("%02x",bytes[i]);puts("");}
                if(n>=3 && bytes[0]==5) {int p=bytes[1]|(bytes[2]<<8);pressure_packets++;if(p<pmin)pmin=p;if(p>pmax)pmax=p;}
            }
        }
        for(int i=1;i<3;i++) if(fds[i].revents&POLLIN) {
            struct input_event ev;
            while(read(fds[i].fd,&ev,sizeof(ev))==sizeof(ev)) {
                events[i-1]++;if(ev.type==EV_KEY&&ev.code==BTN_TOUCH&&ev.value)contact[i-1]++;
                if(events[i-1]<16)printf("NVT%d type=%u code=%u value=%d\n",i-1,ev.type,ev.code,ev.value);
            }
        }
        if(fds[0].revents&(POLLHUP|POLLERR|POLLNVAL)) break;
        if(pressure_packets>=300 && events[1]>=1000 && contact[1]>=2) break;
    }
    int restored=set_pro(0);
    printf("Restore transport=%d stylus=%d HID_packets=%u report5=%u pressure_min=%d max=%d NVT_events=%u,%u contacts=%u,%u\n",
        restored,stylus(),packets,pressure_packets,pmin,pmax,events[0],events[1],contact[0],contact[1]);
    close(hid);if(pen0>=0)close(pen0);if(pen1>=0)close(pen1);
    return restored?1:0;
}

/* SPDX-License-Identifier: GPL-2.0-only */
#define SHENG_TOUCHPAD_HOST_TEST
#include "../interfaces/kernel/6.18/helpers/sheng_touchpad_edge.h"
#include "sheng_touchpad_stock_vectors.h"
#include <assert.h>
int main(void) {
 struct sheng_edge_filter f = {0}, before;
 u8 p[21] = {25}, copy[21];
 unsigned int len,count,id;
 for (len=0;len<40;len++) for (count=0;count<256;count++) for (id=0;id<256;id++) {
  memset(p,0,21);p[0]=25;p[20]=count;p[3]=id;before=f;memcpy(copy,p,21);
  int r=sheng_touchpad_edge(&f,p,len);
  if(len!=21 || count>3 || (count && id>=3) || count>2 || (count==2 && id==0)) {
   assert(r==-EINVAL);assert(!memcmp(&f,&before,sizeof(f)));assert(!memcmp(p,copy,21));
  }
 }
 assert(sheng_touchpad_edge(NULL,p,21)==-EINVAL);
 assert(sheng_touchpad_edge(&f,NULL,21)==-EINVAL);
 unsigned int last=~0U;
 for (unsigned int i=0;i<sizeof(sheng_edge_vectors)/sizeof(sheng_edge_vectors[0]);i++) {
  const struct sheng_edge_golden *v=&sheng_edge_vectors[i];
  if(v->trial!=last) { memset(&f,0,sizeof(f));memcpy(f.param,sheng_edge_golden_params[v->trial],sizeof(f.param));last=v->trial; }
  memcpy(p,v->input,21);assert(sheng_touchpad_edge(&f,p,21)==v->result);assert(!memcmp(p,v->output,21));
 }
 return 0;
}

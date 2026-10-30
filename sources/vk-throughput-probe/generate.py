from pathlib import Path
import shutil
LAB=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent
source=(LAB/'sources/vk-offscreen-x64/vk_offscreen_x64.c').read_text()
source=source.replace('#define FB_WIDTH 64','#define FB_WIDTH bench_width').replace('#define FB_HEIGHT 64','#define FB_HEIGHT bench_height')
source=source.replace('int main(void) {','''int main(void) {
    if(str_contains(GetCommandLineA(),"--720p")){bench_width=1280;bench_height=720;}
    if(str_contains(GetCommandLineA(),"--360p")){bench_width=640;bench_height=360;}
    if(str_contains(GetCommandLineA(),"--frames20"))bench_requested=20;
    if(str_contains(GetCommandLineA(),"--1080p")){bench_width=1920;bench_height=1080;}
    if(str_contains(GetCommandLineA(),"--instances20"))bench_instances=20;
    if(str_contains(GetCommandLineA(),"--instances100"))bench_instances=100;
    if(str_contains(GetCommandLineA(),"--instances500"))bench_instances=500;
''')
source=source.replace('    /* Step 6: Shaders & Graphics Pipeline */','    uint64_t pipeline_start=bench_clock();\n    /* Step 6: Shaders & Graphics Pipeline */')
source=source.replace('    /* Step 7:', '    /* Step 7:',1)
# Pipeline timing ends immediately after graphics-pipeline creation, before buffers.
pos=source.index('    VkBufferCreateInfo vbInfo;')
source=source[:pos]+'    uint64_t pipeline_end=bench_clock();\n'+source[pos:]
extra=r'''
__declspec(dllimport) int QueryPerformanceCounter(long long *);
__declspec(dllimport) int QueryPerformanceFrequency(long long *);
__declspec(dllimport) unsigned long long GetTickCount64(void);
static int str_contains(const char *s,const char *key){for(;s&&*s;s++){unsigned i=0;while(key[i]&&s[i]==key[i])i++;if(!key[i])return 1;}return 0;}
static unsigned bench_width=64,bench_height=64,bench_requested=120,bench_instances=1;
static unsigned char bench_snapshot[1920*1080*4];
static uint64_t starts[128],ends[128];
static uint64_t bench_clock(void){long long v;if(!QueryPerformanceCounter(&v)||v<0)ExitProcess(60);return (uint64_t)v;}
static void bench_num(uint64_t n){char b[24];unsigned i=0;do{b[i++]=(char)('0'+n%10);n/=10;}while(n);while(i){char c[2]={b[--i],0};print_str(c);}}
static void bench_check(VkResult result,const char *name){if(result!=VK_SUCCESS){print_str("BENCH_VK_FAIL call=");print_str(name);print_str(" result=");print_int(result);print_str("\n");ExitProcess(61);}}
static void dump_frames(const char *group,unsigned count,unsigned warm){
 for(unsigned i=0;i<count;i++){
  print_str("BENCH_FRAME group=");print_str(group);print_str(" index=");bench_num(i);
  print_str(" phase=");print_str(i==0?"first":i<=warm?"warmup":"steady");
  print_str(" ticks=");bench_num(ends[i]-starts[i]);print_str(" start=");bench_num(starts[i]);print_str(" end=");bench_num(ends[i]);print_str("\n");
 }
}
'''
source=source.replace('/* Vulkan function pointer declarations */',extra+'\n/* Vulkan function pointer declarations */')
source=source.replace('    VkCommandBufferBeginInfo beginInfo;', '    VkCommandBufferBeginInfo beginInfo;',1)
start=source.index('    VkCommandBufferBeginInfo beginInfo;')
end=source.index('    /* Step 11: Cleanup */')
loop=r'''
    PFN_vkResetCommandBuffer reset_cmd=(PFN_vkResetCommandBuffer)GetProcAddress(hVk,"vkResetCommandBuffer");
    PFN_vkResetFences reset_fences=(PFN_vkResetFences)GetProcAddress(hVk,"vkResetFences");
    if(!reset_cmd||!reset_fences)ExitProcess(62);
    long long signed_freq;if(!QueryPerformanceFrequency(&signed_freq)||signed_freq<=0)ExitProcess(60);
    uint64_t freq=(uint64_t)signed_freq,begin_tick=bench_clock();
    uint64_t begin_ms=GetTickCount64();
    print_str("BENCH_CONFIG width=");bench_num(FB_WIDTH);print_str(" height=");bench_num(FB_HEIGHT);
    print_str(" frames=");bench_num(bench_requested);print_str(" warmup=5 frequency=");bench_num(freq);
    print_str(" pipeline_ticks=");bench_num(pipeline_end-pipeline_start);print_str("\n");
    print_str("BENCH_WORKLOAD instances=");bench_num(bench_instances);print_str(" triangles_per_draw=");bench_num(bench_instances);print_str("\n");
    VkFenceCreateInfo fi={0};fi.sType=VK_STRUCTURE_TYPE_FENCE_CREATE_INFO;
    VkFence fence=0;bench_check(pvkCreateFence(device,&fi,0,&fence),"vkCreateFence");
    unsigned draw_count=0,submit_count=0,validations=0;
    const char *groups[3]={"draw","readback","clear"};
    const char *files[3]={"C:\\bench-draw.raw","C:\\bench-readback.raw","C:\\bench-clear.raw"};
    for(unsigned g=0;g<3;g++){
      unsigned count=bench_requested,measured=0;uint64_t max_pilot=1,steady_start=0,steady_end=0;
      print_str("BENCH_GROUP_BEGIN group=");print_str(groups[g]);print_str("\n");
      for(unsigned frame=0;frame<6+count+1;frame++){
        int validation=(frame==6+count);
        int copy=(g==1||validation);
        uint64_t t0=bench_clock();if(frame==6)steady_start=t0;
        bench_check(reset_cmd(cmdBuffer,0),"vkResetCommandBuffer");
        bench_check(reset_fences(device,1,&fence),"vkResetFences");
        VkCommandBufferBeginInfo bi={0};bi.sType=VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO;
        bench_check(pvkBeginCommandBuffer(cmdBuffer,&bi),"vkBeginCommandBuffer");
        VkClearValue clear;clear.color.float32[0]=0;clear.color.float32[1]=0;clear.color.float32[2]=.5f;clear.color.float32[3]=1;
        VkRenderPassBeginInfo rp={0};rp.sType=VK_STRUCTURE_TYPE_RENDER_PASS_BEGIN_INFO;rp.renderPass=renderPass;rp.framebuffer=framebuffer;
        rp.renderArea.extent.width=FB_WIDTH;rp.renderArea.extent.height=FB_HEIGHT;rp.clearValueCount=1;rp.pClearValues=&clear;
        pvkCmdBeginRenderPass(cmdBuffer,&rp,VK_SUBPASS_CONTENTS_INLINE);
        pvkCmdBindPipeline(cmdBuffer,VK_PIPELINE_BIND_POINT_GRAPHICS,graphicsPipeline);
        VkDeviceSize offsets[1]={0};pvkCmdBindVertexBuffers(cmdBuffer,0,1,&vertexBuffer,offsets);
        if(g!=2){pvkCmdDraw(cmdBuffer,3,bench_instances,0,0);draw_count++;}
        pvkCmdEndRenderPass(cmdBuffer);
        if(copy){
          VkImageMemoryBarrier bar={0};bar.sType=VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER;
          bar.oldLayout=VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL;bar.newLayout=VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL;
          bar.srcQueueFamilyIndex=bar.dstQueueFamilyIndex=VK_QUEUE_FAMILY_IGNORED;bar.image=offscreenImage;
          bar.subresourceRange.aspectMask=VK_IMAGE_ASPECT_COLOR_BIT;bar.subresourceRange.levelCount=bar.subresourceRange.layerCount=1;
          bar.srcAccessMask=VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT;bar.dstAccessMask=VK_ACCESS_TRANSFER_READ_BIT;
          pvkCmdPipelineBarrier(cmdBuffer,VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT,VK_PIPELINE_STAGE_TRANSFER_BIT,0,0,0,0,0,1,&bar);
          VkBufferImageCopy region={0};region.imageSubresource.aspectMask=VK_IMAGE_ASPECT_COLOR_BIT;region.imageSubresource.layerCount=1;
          region.imageExtent.width=FB_WIDTH;region.imageExtent.height=FB_HEIGHT;region.imageExtent.depth=1;
          pvkCmdCopyImageToBuffer(cmdBuffer,offscreenImage,VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,stagingBuffer,1,&region);
          VkBufferMemoryBarrier host_barrier={0};host_barrier.sType=VK_STRUCTURE_TYPE_BUFFER_MEMORY_BARRIER;
          host_barrier.srcAccessMask=VK_ACCESS_TRANSFER_WRITE_BIT;host_barrier.dstAccessMask=VK_ACCESS_HOST_READ_BIT;
          host_barrier.srcQueueFamilyIndex=host_barrier.dstQueueFamilyIndex=VK_QUEUE_FAMILY_IGNORED;
          host_barrier.buffer=stagingBuffer;host_barrier.size=VK_WHOLE_SIZE;
          pvkCmdPipelineBarrier(cmdBuffer,VK_PIPELINE_STAGE_TRANSFER_BIT,VK_PIPELINE_STAGE_HOST_BIT,0,0,0,1,&host_barrier,0,0);
        }
        bench_check(pvkEndCommandBuffer(cmdBuffer),"vkEndCommandBuffer");
        VkSubmitInfo si={0};si.sType=VK_STRUCTURE_TYPE_SUBMIT_INFO;si.commandBufferCount=1;si.pCommandBuffers=&cmdBuffer;
        bench_check(pvkQueueSubmit(graphicsQueue,1,&si,fence),"vkQueueSubmit");submit_count++;
        bench_check(pvkWaitForFences(device,1,&fence,VK_TRUE,5000000000ULL),"vkWaitForFences");
        if(copy){
          unsigned char *pixels=0;bench_check(pvkMapMemory(device,stagingBufferMemory,0,sbMemReqs.size,0,(void**)&pixels),"vkMapMemory");
          if(!pixels)ExitProcess(63);
          VkMappedMemoryRange range={0};range.sType=VK_STRUCTURE_TYPE_MAPPED_MEMORY_RANGE;range.memory=stagingBufferMemory;range.size=VK_WHOLE_SIZE;
          bench_check(pvkInvalidateMappedMemoryRanges(device,1,&range),"vkInvalidateMappedMemoryRanges");
          memcpy(bench_snapshot,pixels,FB_SIZE);
          __asm__ __volatile__("" ::: "memory");
          pvkUnmapMemory(device,stagingBufferMemory);
        }
        uint64_t t1=bench_clock();if(t1<t0)ExitProcess(64);
        if(!validation){starts[frame]=t0;ends[frame]=t1;measured++;
          if(frame>0 && frame<6 && t1-t0>max_pilot)max_pilot=t1-t0;
        }
        if(frame==5){
          /* Conservative per-group ten-second budget, two-times pilot safety factor. */
          uint64_t affordable=freq*10/(max_pilot*2);
          if(affordable<20){dump_frames(groups[g],6,5);print_str("BENCH_ABORT_BUDGET group=");print_str(groups[g]);print_str(" max_pilot_ticks=");bench_num(max_pilot);print_str("\n");ExitProcess(70);}
          if(affordable<count)count=(unsigned)affordable;
          print_str("BENCH_GROUP group=");print_str(groups[g]);print_str(" frames=");bench_num(count);
          print_str(" budget_reduced=");bench_num(count<bench_requested);print_str(" max_pilot_ticks=");bench_num(max_pilot);print_str("\n");
        }
        if(frame==5+count)steady_end=t1;
        if(validation){
          unsigned xs[8]={32,32,22,42,5,59,5,59};unsigned ys[8]={38,25,44,44,5,5,59,59};
          for(unsigned k=0;k<8;k++){
            unsigned x=xs[k]*FB_WIDTH/64,y=ys[k]*FB_HEIGHT/64,idx=(y*FB_WIDTH+x)*4;
            unsigned red=(g!=2 && k<4)?255:0,blue=(g!=2 && k<4)?0:128;
            if(bench_snapshot[idx]!=red || bench_snapshot[idx+1]!=0 || bench_snapshot[idx+2]!=blue || bench_snapshot[idx+3]!=255){print_str("BENCH_PIXEL_FAIL\n");ExitProcess(65);}
          }
          HANDLE f=CreateFileA(files[g],GENERIC_WRITE,0,0,CREATE_ALWAYS,FILE_ATTRIBUTE_NORMAL,0);
          DWORD written=0;if(f==(HANDLE)(long long)-1||!WriteFile(f,bench_snapshot,FB_SIZE,&written,0)||written!=FB_SIZE)ExitProcess(66);CloseHandle(f);validations++;
        }
      }
      dump_frames(groups[g],measured,5);
      print_str("BENCH_GROUP_END group=");print_str(groups[g]);print_str(" steady_wall_ticks=");bench_num(steady_end-steady_start);print_str("\n");
    }
    print_str("BENCH_CLOCK qpc_elapsed_ticks=");bench_num(bench_clock()-begin_tick);print_str(" tick_elapsed_ms=");bench_num(GetTickCount64()-begin_ms);print_str("\n");
    print_str("BENCH_DONE total_draws=");bench_num(draw_count);print_str(" total_submits=");bench_num(submit_count);print_str(" validations=");bench_num(validations);print_str("\n");
'''
source=source[:start]+loop+source[end:]
source=source.replace('    poolInfo.sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO;', '    poolInfo.sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO;\n    poolInfo.flags = VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT;')
source=source.replace('WIN_X64_OFFSCREEN_OK','WIN_X64_THROUGHPUT_OK')
(OUT/'vk_throughput_x64.c').write_text(source)
(OUT/'shaders').mkdir(exist_ok=True)
shutil.copy2(LAB/'sources/vk-offscreen-x64/shaders/shaders_spv.h',OUT/'shaders/shaders_spv.h')
text=(LAB/'sources/vk-offscreen-x64/kernel32.def').read_text()+'QueryPerformanceCounter\nQueryPerformanceFrequency\nGetTickCount64\n'
(OUT/'kernel32.def').write_text(text)
print('Generated isolated benchmark, original source unchanged')

/*
 * sources/vk-offscreen-probe/vk_offscreen_x64.c
 *
 * Windows X64 Console Application for Vulkan Offscreen Triangle Rendering & Readback.
 * Zero MSVC CRT runtime dependencies. Compiles with clang + lld-link.
 * Uses official Khronos vulkan_core.h for robust structure alignments and PFN signatures.
 *
 * Steps:
 * 1. Load vulkan-1.dll and resolve entry points.
 * 2. Create VkInstance (Vulkan 1.0).
 * 3. Enumerate physical device (CPU llvmpipe) and select graphics queue family.
 * 4. Create VkDevice and retrieve VkQueue.
 * 5. Create 64x64 R8G8B8A8_UNORM offscreen image, allocate/bind device memory, create image view.
 * 6. Create render pass (clear to Dark Blue: 0, 0, 128, 255) and framebuffer.
 * 7. Create shader modules (triangle.vert.spv and triangle.frag.spv) and graphics pipeline.
 * 8. Create vertex buffer with 3 vertices (NDC: (0,-0.6), (0.6,0.6), (-0.6,0.6)) and staging buffer.
 * 9. Record command buffer: begin renderpass, bind pipeline, bind vertex buffer, vkCmdDraw(3),
 *    end renderpass, image memory barrier (ATTACHMENT_OPTIMAL -> TRANSFER_SRC_OPTIMAL),
 *    copy image to staging buffer.
 * 10. Submit queue with VkFence, wait on fence (10s timeout).
 * 11. Map staging buffer memory, verify interior triangle pixels (Red: 255, 0, 0, 255)
 *     and exterior background pixels (Dark Blue: 0, 0, 128, 255).
 * 12. Write raw 16384-byte framebuffer to C:\\framebuffer.raw.
 * 13. Clean up all Vulkan objects and exit:
 *     Exit 0: Full Success (WIN_ARM64_INPROC_FRAME_OK)
 *     Exit 10: Failed loading vulkan-1.dll
 *     Exit 11: Failed resolving function pointer
 *     Exit 12: vkCreateInstance failed
 *     Exit 13: vkEnumeratePhysicalDevices failed or count is 0
 *     Exit 14: Failed finding graphics queue family
 *     Exit 15: vkCreateDevice failed
 *     Exit 16: Image/ImageView/RenderPass/Framebuffer creation failed
 *     Exit 17: Shader/Pipeline creation failed
 *     Exit 18: Buffer/Memory creation failed
 *     Exit 19: Command buffer recording or submission failed
 *     Exit 20: Fence wait timeout or failure
 *     Exit 21: Pixel validation failed (Interior sample did not match Red)
 *     Exit 22: Pixel validation failed (Exterior sample did not match Background)
 */

/* MSVC x64 floating-point ABI marker for a CRT-free executable. */
int _fltused = 0;

typedef unsigned long DWORD;
typedef unsigned long long QWORD;
typedef void* HANDLE;
typedef void* HMODULE;
typedef int (*FARPROC)(void);

#define STD_OUTPUT_HANDLE ((DWORD)-11)
#define GENERIC_WRITE (0x40000000L)
#define CREATE_ALWAYS 2
#define FILE_ATTRIBUTE_NORMAL 0x00000080

__declspec(dllimport) HANDLE __stdcall GetStdHandle(DWORD nStdHandle);
__declspec(dllimport) int __stdcall WriteFile(HANDLE hFile, const void* lpBuffer, DWORD nNumberOfBytesToWrite, DWORD* lpNumberOfBytesWritten, void* lpOverlapped);
__declspec(dllimport) HANDLE __stdcall CreateFileA(const char* lpFileName, DWORD dwDesiredAccess, DWORD dwShareMode, void* lpSecurityAttributes, DWORD dwCreationDisposition, DWORD dwFlagsAndAttributes, HANDLE hTemplateFile);
__declspec(dllimport) int __stdcall CloseHandle(HANDLE hObject);
__declspec(dllimport) HMODULE __stdcall LoadLibraryA(const char* lpLibFileName);
__declspec(dllimport) FARPROC __stdcall GetProcAddress(HMODULE hModule, const char* lpProcName);
__declspec(dllimport) DWORD __stdcall GetLastError(void);
__declspec(dllimport) void __stdcall ExitProcess(DWORD uExitCode);
__declspec(dllimport) char* __stdcall GetCommandLineA(void);

void* memset(void* dest, int c, QWORD count) {
    unsigned char* p = (unsigned char*)dest;
    while (count--) *p++ = (unsigned char)c;
    return dest;
}

void* memcpy(void* dest, const void* src, QWORD count) {
    unsigned char* d = (unsigned char*)dest;
    const unsigned char* s = (const unsigned char*)src;
    while (count--) *d++ = *s++;
    return dest;
}

void __chkstk(void) {}

#define VK_NO_PROTOTYPES
#include <vulkan/vulkan_core.h>

/* Embedded validated SPIR-V byte arrays */
#include "shaders_spv.h"

#define FB_WIDTH bench_width
#define FB_HEIGHT bench_height
#define FB_CHANNELS 4
#define FB_SIZE (FB_WIDTH * FB_HEIGHT * FB_CHANNELS)

static void print_str(const char* s) {
    HANDLE hOut = GetStdHandle(STD_OUTPUT_HANDLE);
    DWORD len = 0;
    while (s[len]) len++;
    DWORD wrote = 0;
    WriteFile(hOut, s, len, &wrote, 0);
}

static void print_uint(unsigned int val) {
    char buf[16];
    int idx = 0;
    if (val == 0) {
        buf[idx++] = '0';
    } else {
        char tmp[16];
        int tlen = 0;
        while (val > 0) {
            tmp[tlen++] = '0' + (val % 10);
            val /= 10;
        }
        for (int i = tlen - 1; i >= 0; i--) buf[idx++] = tmp[i];
    }
    buf[idx] = '\0';
    print_str(buf);
}

static void print_hex(unsigned int val) {
    char buf[12];
    buf[0] = '0'; buf[1] = 'x';
    const char* hexDigits = "0123456789abcdef";
    for (int i = 7; i >= 0; i--) {
        buf[2 + i] = hexDigits[val & 0xf];
        val >>= 4;
    }
    buf[10] = '\0';
    print_str(buf);
}

static void print_int(int val) {
    if (val < 0) {
        print_str("-");
        print_uint((unsigned int)(-val));
    } else {
        print_uint((unsigned int)val);
    }
}


__declspec(dllimport) int QueryPerformanceCounter(long long *);
__declspec(dllimport) int QueryPerformanceFrequency(long long *);
__declspec(dllimport) unsigned long long GetTickCount64(void);
static int str_contains(const char *s,const char *key){for(;s&&*s;s++){unsigned i=0;while(key[i]&&s[i]==key[i])i++;if(!key[i])return 1;}return 0;}
struct PixelPacket {uint64_t ready,seq,phase,width,height,pitch,payload_bytes;unsigned char pixels[1920*1080*4];};
volatile struct PixelPacket inproc_packet;
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

/* Vulkan function pointer declarations */
static PFN_vkCreateInstance pvkCreateInstance;
static PFN_vkDestroyInstance pvkDestroyInstance;
static PFN_vkEnumeratePhysicalDevices pvkEnumeratePhysicalDevices;
static PFN_vkGetPhysicalDeviceProperties pvkGetPhysicalDeviceProperties;
static PFN_vkGetPhysicalDeviceQueueFamilyProperties pvkGetPhysicalDeviceQueueFamilyProperties;
static PFN_vkGetPhysicalDeviceMemoryProperties pvkGetPhysicalDeviceMemoryProperties;
static PFN_vkCreateDevice pvkCreateDevice;
static PFN_vkDestroyDevice pvkDestroyDevice;
static PFN_vkGetDeviceQueue pvkGetDeviceQueue;
static PFN_vkCreateImage pvkCreateImage;
static PFN_vkDestroyImage pvkDestroyImage;
static PFN_vkGetImageMemoryRequirements pvkGetImageMemoryRequirements;
static PFN_vkBindImageMemory pvkBindImageMemory;
static PFN_vkCreateImageView pvkCreateImageView;
static PFN_vkDestroyImageView pvkDestroyImageView;
static PFN_vkCreateRenderPass pvkCreateRenderPass;
static PFN_vkDestroyRenderPass pvkDestroyRenderPass;
static PFN_vkCreateFramebuffer pvkCreateFramebuffer;
static PFN_vkDestroyFramebuffer pvkDestroyFramebuffer;
static PFN_vkCreateShaderModule pvkCreateShaderModule;
static PFN_vkDestroyShaderModule pvkDestroyShaderModule;
static PFN_vkCreatePipelineLayout pvkCreatePipelineLayout;
static PFN_vkDestroyPipelineLayout pvkDestroyPipelineLayout;
static PFN_vkCreateGraphicsPipelines pvkCreateGraphicsPipelines;
static PFN_vkDestroyPipeline pvkDestroyPipeline;
static PFN_vkCreateBuffer pvkCreateBuffer;
static PFN_vkDestroyBuffer pvkDestroyBuffer;
static PFN_vkGetBufferMemoryRequirements pvkGetBufferMemoryRequirements;
static PFN_vkBindBufferMemory pvkBindBufferMemory;
static PFN_vkAllocateMemory pvkAllocateMemory;
static PFN_vkFreeMemory pvkFreeMemory;
static PFN_vkMapMemory pvkMapMemory;
static PFN_vkUnmapMemory pvkUnmapMemory;
static PFN_vkInvalidateMappedMemoryRanges pvkInvalidateMappedMemoryRanges;
static PFN_vkCreateCommandPool pvkCreateCommandPool;
static PFN_vkDestroyCommandPool pvkDestroyCommandPool;
static PFN_vkAllocateCommandBuffers pvkAllocateCommandBuffers;
static PFN_vkBeginCommandBuffer pvkBeginCommandBuffer;
static PFN_vkEndCommandBuffer pvkEndCommandBuffer;
static PFN_vkCmdBeginRenderPass pvkCmdBeginRenderPass;
static PFN_vkCmdEndRenderPass pvkCmdEndRenderPass;
static PFN_vkCmdBindPipeline pvkCmdBindPipeline;
static PFN_vkCmdBindVertexBuffers pvkCmdBindVertexBuffers;
static PFN_vkCmdDraw pvkCmdDraw;
static PFN_vkCmdPipelineBarrier pvkCmdPipelineBarrier;
static PFN_vkCmdCopyImageToBuffer pvkCmdCopyImageToBuffer;
static PFN_vkCreateFence pvkCreateFence;
static PFN_vkDestroyFence pvkDestroyFence;
static PFN_vkWaitForFences pvkWaitForFences;
static PFN_vkQueueSubmit pvkQueueSubmit;
static PFN_vkQueueWaitIdle pvkQueueWaitIdle;

static VkPhysicalDeviceMemoryProperties memProperties;

static uint32_t find_memory_type(uint32_t typeFilter, VkMemoryPropertyFlags properties) {
    for (uint32_t i = 0; i < memProperties.memoryTypeCount; i++) {
        if ((typeFilter & (1 << i)) && (memProperties.memoryTypes[i].propertyFlags & properties) == properties) {
            return i;
        }
    }
    /* Fallback: any matching typeFilter if specific properties not strictly met */
    for (uint32_t i = 0; i < memProperties.memoryTypeCount; i++) {
        if (typeFilter & (1 << i)) {
            return i;
        }
    }
    return 0xFFFFFFFF;
}

int main(void) {
    if(str_contains(GetCommandLineA(),"--720p")){bench_width=1280;bench_height=720;}
    if(str_contains(GetCommandLineA(),"--360p")){bench_width=640;bench_height=360;}
    if(str_contains(GetCommandLineA(),"--frames20"))bench_requested=20;
    if(str_contains(GetCommandLineA(),"--1080p")){bench_width=1920;bench_height=1080;}
    if(str_contains(GetCommandLineA(),"--instances20"))bench_instances=20;
    if(str_contains(GetCommandLineA(),"--instances100"))bench_instances=100;
    if(str_contains(GetCommandLineA(),"--instances500"))bench_instances=500;

    int opt_skip_draw = 0;
    int opt_bad_expect = 0;

    const char* cmdline = GetCommandLineA();
    if (cmdline) {
        for (int i = 0; cmdline[i]; i++) {
            if (cmdline[i] == '-' && cmdline[i+1] == '-' &&
                cmdline[i+2] == 's' && cmdline[i+3] == 'k' &&
                cmdline[i+4] == 'i' && cmdline[i+5] == 'p') {
                opt_skip_draw = 1;
            }
            if (cmdline[i] == '-' && cmdline[i+1] == '-' &&
                cmdline[i+2] == 'b' && cmdline[i+3] == 'a' &&
                cmdline[i+4] == 'd') {
                opt_bad_expect = 1;
            }
        }
    }

    print_str("==========================================================\n");
    print_str("[OFFSCREEN_VK] Starting Windows X64 Offscreen Vulkan Triangle Probe\n");
    print_str("==========================================================\n");

    /* Step 1: Loading vulkan-1.dll */
    print_str("[OFFSCREEN_VK] Step 1: Loading vulkan-1.dll and resolving entry points...\n");
    HMODULE hVk = LoadLibraryA("vulkan-1.dll");
    if (!hVk) {
        print_str("[OFFSCREEN_VK] ERROR: LoadLibraryA(\"vulkan-1.dll\") failed! Error code: ");
        print_uint(GetLastError());
        print_str("\n");
        ExitProcess(10);
    }
    print_str("[OFFSCREEN_VK] SUCCESS: vulkan-1.dll loaded at ");
    print_hex((unsigned int)(QWORD)hVk);
    print_str("\n");

#define RESOLVE_VK(fn) \
    p##fn = (PFN_##fn)GetProcAddress(hVk, #fn); \
    if (!p##fn) { \
        print_str("[OFFSCREEN_VK] ERROR: Failed resolving function " #fn "\n"); \
        ExitProcess(11); \
    }

    RESOLVE_VK(vkCreateInstance);
    RESOLVE_VK(vkDestroyInstance);
    RESOLVE_VK(vkEnumeratePhysicalDevices);
    RESOLVE_VK(vkGetPhysicalDeviceProperties);
    RESOLVE_VK(vkGetPhysicalDeviceQueueFamilyProperties);
    RESOLVE_VK(vkGetPhysicalDeviceMemoryProperties);
    RESOLVE_VK(vkCreateDevice);
    RESOLVE_VK(vkDestroyDevice);
    RESOLVE_VK(vkGetDeviceQueue);
    RESOLVE_VK(vkCreateImage);
    RESOLVE_VK(vkDestroyImage);
    RESOLVE_VK(vkGetImageMemoryRequirements);
    RESOLVE_VK(vkBindImageMemory);
    RESOLVE_VK(vkCreateImageView);
    RESOLVE_VK(vkDestroyImageView);
    RESOLVE_VK(vkCreateRenderPass);
    RESOLVE_VK(vkDestroyRenderPass);
    RESOLVE_VK(vkCreateFramebuffer);
    RESOLVE_VK(vkDestroyFramebuffer);
    RESOLVE_VK(vkCreateShaderModule);
    RESOLVE_VK(vkDestroyShaderModule);
    RESOLVE_VK(vkCreatePipelineLayout);
    RESOLVE_VK(vkDestroyPipelineLayout);
    RESOLVE_VK(vkCreateGraphicsPipelines);
    RESOLVE_VK(vkDestroyPipeline);
    RESOLVE_VK(vkCreateBuffer);
    RESOLVE_VK(vkDestroyBuffer);
    RESOLVE_VK(vkGetBufferMemoryRequirements);
    RESOLVE_VK(vkBindBufferMemory);
    RESOLVE_VK(vkAllocateMemory);
    RESOLVE_VK(vkFreeMemory);
    RESOLVE_VK(vkMapMemory);
    RESOLVE_VK(vkUnmapMemory);
    RESOLVE_VK(vkInvalidateMappedMemoryRanges);
    RESOLVE_VK(vkCreateCommandPool);
    RESOLVE_VK(vkDestroyCommandPool);
    RESOLVE_VK(vkAllocateCommandBuffers);
    RESOLVE_VK(vkBeginCommandBuffer);
    RESOLVE_VK(vkEndCommandBuffer);
    RESOLVE_VK(vkCmdBeginRenderPass);
    RESOLVE_VK(vkCmdEndRenderPass);
    RESOLVE_VK(vkCmdBindPipeline);
    RESOLVE_VK(vkCmdBindVertexBuffers);
    RESOLVE_VK(vkCmdDraw);
    RESOLVE_VK(vkCmdPipelineBarrier);
    RESOLVE_VK(vkCmdCopyImageToBuffer);
    RESOLVE_VK(vkCreateFence);
    RESOLVE_VK(vkDestroyFence);
    RESOLVE_VK(vkWaitForFences);
    RESOLVE_VK(vkQueueSubmit);
    RESOLVE_VK(vkQueueWaitIdle);

    print_str("[OFFSCREEN_VK] SUCCESS: All 40 Vulkan 1.0 entry points resolved.\n");

    /* Step 2: Create VkInstance */
    print_str("[OFFSCREEN_VK] Step 2: Creating VkInstance...\n");
    VkApplicationInfo appInfo;
    memset(&appInfo, 0, sizeof(appInfo));
    appInfo.sType = VK_STRUCTURE_TYPE_APPLICATION_INFO;
    appInfo.pApplicationName = "ProtonLabOffscreenTriangle";
    appInfo.applicationVersion = VK_MAKE_VERSION(1, 0, 0);
    appInfo.pEngineName = "None";
    appInfo.engineVersion = VK_MAKE_VERSION(1, 0, 0);
    appInfo.apiVersion = VK_API_VERSION_1_0;

    VkInstanceCreateInfo instCreateInfo;
    memset(&instCreateInfo, 0, sizeof(instCreateInfo));
    instCreateInfo.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO;
    instCreateInfo.pApplicationInfo = &appInfo;

    VkInstance instance = 0;
    VkResult res = pvkCreateInstance(&instCreateInfo, 0, &instance);
    if (res != VK_SUCCESS || !instance) {
        print_str("[OFFSCREEN_VK] ERROR: vkCreateInstance failed! VkResult=");
        print_int(res);
        print_str("\n");
        ExitProcess(12);
    }
    print_str("[OFFSCREEN_VK] SUCCESS: VkInstance created at ");
    print_hex((unsigned int)(QWORD)instance);
    print_str("\n");

    /* Step 3: Enumerate Physical Device & Select Graphics Queue */
    print_str("[OFFSCREEN_VK] Step 3: Enumerating physical devices...\n");
    uint32_t devCount = 0;
    res = pvkEnumeratePhysicalDevices(instance, &devCount, 0);
    if (res != VK_SUCCESS || devCount == 0) {
        print_str("[OFFSCREEN_VK] ERROR: vkEnumeratePhysicalDevices count failed! res=");
        print_int(res);
        print_str("\n");
        ExitProcess(13);
    }
    VkPhysicalDevice physicalDevices[4];
    res = pvkEnumeratePhysicalDevices(instance, &devCount, physicalDevices);
    if (res != VK_SUCCESS) {
        print_str("[OFFSCREEN_VK] ERROR: vkEnumeratePhysicalDevices failed! res=");
        print_int(res);
        print_str("\n");
        ExitProcess(13);
    }
    VkPhysicalDevice physDev = physicalDevices[0];

    VkPhysicalDeviceProperties props;
    pvkGetPhysicalDeviceProperties(physDev, &props);
    print_str("[OFFSCREEN_VK] Selected Device: ");
    print_str(props.deviceName);
    print_str(" (Type=");
    print_uint(props.deviceType);
    print_str(")\n");

    pvkGetPhysicalDeviceMemoryProperties(physDev, &memProperties);

    /* Find Graphics Queue Family */
    uint32_t queueFamilyCount = 0;
    pvkGetPhysicalDeviceQueueFamilyProperties(physDev, &queueFamilyCount, 0);
    VkQueueFamilyProperties queueFamilies[8];
    if (queueFamilyCount > 8) queueFamilyCount = 8;
    pvkGetPhysicalDeviceQueueFamilyProperties(physDev, &queueFamilyCount, queueFamilies);

    uint32_t graphicsQueueIndex = 0xFFFFFFFF;
    for (uint32_t i = 0; i < queueFamilyCount; i++) {
        if (queueFamilies[i].queueFlags & VK_QUEUE_GRAPHICS_BIT) {
            graphicsQueueIndex = i;
            break;
        }
    }
    if (graphicsQueueIndex == 0xFFFFFFFF) {
        print_str("[OFFSCREEN_VK] ERROR: No graphics queue family found!\n");
        ExitProcess(14);
    }
    print_str("[OFFSCREEN_VK] Selected Graphics Queue Family Index: ");
    print_uint(graphicsQueueIndex);
    print_str("\n");

    /* Step 4: Create VkDevice and retrieve VkQueue */
    print_str("[OFFSCREEN_VK] Step 4: Creating VkDevice and VkQueue...\n");
    float queuePriority = 1.0f;
    VkDeviceQueueCreateInfo queueCreateInfo;
    memset(&queueCreateInfo, 0, sizeof(queueCreateInfo));
    queueCreateInfo.sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO;
    queueCreateInfo.queueFamilyIndex = graphicsQueueIndex;
    queueCreateInfo.queueCount = 1;
    queueCreateInfo.pQueuePriorities = &queuePriority;

    VkDeviceCreateInfo deviceCreateInfo;
    memset(&deviceCreateInfo, 0, sizeof(deviceCreateInfo));
    deviceCreateInfo.sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO;
    deviceCreateInfo.queueCreateInfoCount = 1;
    deviceCreateInfo.pQueueCreateInfos = &queueCreateInfo;

    VkDevice device = 0;
    res = pvkCreateDevice(physDev, &deviceCreateInfo, 0, &device);
    if (res != VK_SUCCESS || !device) {
        print_str("[OFFSCREEN_VK] ERROR: vkCreateDevice failed! res=");
        print_int(res);
        print_str("\n");
        ExitProcess(15);
    }
    VkQueue graphicsQueue = 0;
    pvkGetDeviceQueue(device, graphicsQueueIndex, 0, &graphicsQueue);
    print_str("[OFFSCREEN_VK] SUCCESS: Device and Graphics Queue created.\n");

    /* Step 5: Offscreen Image, Memory, View, RenderPass, and Framebuffer */
    print_str("[OFFSCREEN_VK] Step 5: Creating 64x64 RGBA8 offscreen image, render pass, and framebuffer...\n");
    VkImageCreateInfo imageInfo;
    memset(&imageInfo, 0, sizeof(imageInfo));
    imageInfo.sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO;
    imageInfo.imageType = VK_IMAGE_TYPE_2D;
    imageInfo.format = VK_FORMAT_R8G8B8A8_UNORM;
    imageInfo.extent.width = FB_WIDTH;
    imageInfo.extent.height = FB_HEIGHT;
    imageInfo.extent.depth = 1;
    imageInfo.mipLevels = 1;
    imageInfo.arrayLayers = 1;
    imageInfo.samples = VK_SAMPLE_COUNT_1_BIT;
    imageInfo.tiling = VK_IMAGE_TILING_OPTIMAL;
    imageInfo.usage = VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT | VK_IMAGE_USAGE_TRANSFER_SRC_BIT;
    imageInfo.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
    imageInfo.initialLayout = VK_IMAGE_LAYOUT_UNDEFINED;

    VkImage offscreenImage = 0;
    res = pvkCreateImage(device, &imageInfo, 0, &offscreenImage);
    if (res != VK_SUCCESS) { ExitProcess(16); }

    VkMemoryRequirements imgMemReqs;
    pvkGetImageMemoryRequirements(device, offscreenImage, &imgMemReqs);

    VkMemoryAllocateInfo imgAllocInfo;
    memset(&imgAllocInfo, 0, sizeof(imgAllocInfo));
    imgAllocInfo.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO;
    imgAllocInfo.allocationSize = imgMemReqs.size;
    imgAllocInfo.memoryTypeIndex = find_memory_type(imgMemReqs.memoryTypeBits, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT);

    VkDeviceMemory imageMemory = 0;
    res = pvkAllocateMemory(device, &imgAllocInfo, 0, &imageMemory);
    if (res != VK_SUCCESS) { ExitProcess(16); }
    res = pvkBindImageMemory(device, offscreenImage, imageMemory, 0);
    if (res != VK_SUCCESS) { ExitProcess(16); }

    /* Image View */
    VkImageViewCreateInfo viewInfo;
    memset(&viewInfo, 0, sizeof(viewInfo));
    viewInfo.sType = VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO;
    viewInfo.image = offscreenImage;
    viewInfo.viewType = VK_IMAGE_VIEW_TYPE_2D;
    viewInfo.format = VK_FORMAT_R8G8B8A8_UNORM;
    viewInfo.subresourceRange.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
    viewInfo.subresourceRange.baseMipLevel = 0;
    viewInfo.subresourceRange.levelCount = 1;
    viewInfo.subresourceRange.baseArrayLayer = 0;
    viewInfo.subresourceRange.layerCount = 1;

    VkImageView imageView = 0;
    res = pvkCreateImageView(device, &viewInfo, 0, &imageView);
    if (res != VK_SUCCESS) { ExitProcess(16); }

    /* Render Pass */
    VkAttachmentDescription colorAttachment;
    memset(&colorAttachment, 0, sizeof(colorAttachment));
    colorAttachment.format = VK_FORMAT_R8G8B8A8_UNORM;
    colorAttachment.samples = VK_SAMPLE_COUNT_1_BIT;
    colorAttachment.loadOp = VK_ATTACHMENT_LOAD_OP_CLEAR;
    colorAttachment.storeOp = VK_ATTACHMENT_STORE_OP_STORE;
    colorAttachment.stencilLoadOp = VK_ATTACHMENT_LOAD_OP_DONT_CARE;
    colorAttachment.stencilStoreOp = VK_ATTACHMENT_STORE_OP_DONT_CARE;
    colorAttachment.initialLayout = VK_IMAGE_LAYOUT_UNDEFINED;
    colorAttachment.finalLayout = VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL;

    VkAttachmentReference colorAttachmentRef;
    memset(&colorAttachmentRef, 0, sizeof(colorAttachmentRef));
    colorAttachmentRef.attachment = 0;
    colorAttachmentRef.layout = VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL;

    VkSubpassDescription subpass;
    memset(&subpass, 0, sizeof(subpass));
    subpass.pipelineBindPoint = VK_PIPELINE_BIND_POINT_GRAPHICS;
    subpass.colorAttachmentCount = 1;
    subpass.pColorAttachments = &colorAttachmentRef;

    VkRenderPassCreateInfo renderPassInfo;
    memset(&renderPassInfo, 0, sizeof(renderPassInfo));
    renderPassInfo.sType = VK_STRUCTURE_TYPE_RENDER_PASS_CREATE_INFO;
    renderPassInfo.attachmentCount = 1;
    renderPassInfo.pAttachments = &colorAttachment;
    renderPassInfo.subpassCount = 1;
    renderPassInfo.pSubpasses = &subpass;

    VkRenderPass renderPass = 0;
    res = pvkCreateRenderPass(device, &renderPassInfo, 0, &renderPass);
    if (res != VK_SUCCESS) { ExitProcess(16); }

    /* Framebuffer */
    VkFramebufferCreateInfo fbInfo;
    memset(&fbInfo, 0, sizeof(fbInfo));
    fbInfo.sType = VK_STRUCTURE_TYPE_FRAMEBUFFER_CREATE_INFO;
    fbInfo.renderPass = renderPass;
    fbInfo.attachmentCount = 1;
    fbInfo.pAttachments = &imageView;
    fbInfo.width = FB_WIDTH;
    fbInfo.height = FB_HEIGHT;
    fbInfo.layers = 1;

    VkFramebuffer framebuffer = 0;
    res = pvkCreateFramebuffer(device, &fbInfo, 0, &framebuffer);
    if (res != VK_SUCCESS) { ExitProcess(16); }
    print_str("[OFFSCREEN_VK] SUCCESS: Framebuffer and RenderPass created.\n");

    uint64_t pipeline_start=bench_clock();
    /* Step 6: Shaders & Graphics Pipeline */
    print_str("[OFFSCREEN_VK] Step 6: Creating Shader Modules and Graphics Pipeline...\n");
    VkShaderModuleCreateInfo vertModInfo;
    memset(&vertModInfo, 0, sizeof(vertModInfo));
    vertModInfo.sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO;
    vertModInfo.codeSize = sizeof(triangle_vert_spv);
    vertModInfo.pCode = triangle_vert_spv;

    VkShaderModule vertShaderModule = 0;
    res = pvkCreateShaderModule(device, &vertModInfo, 0, &vertShaderModule);
    if (res != VK_SUCCESS) { ExitProcess(17); }

    VkShaderModuleCreateInfo fragModInfo;
    memset(&fragModInfo, 0, sizeof(fragModInfo));
    fragModInfo.sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO;
    fragModInfo.codeSize = sizeof(triangle_frag_spv);
    fragModInfo.pCode = triangle_frag_spv;

    VkShaderModule fragShaderModule = 0;
    res = pvkCreateShaderModule(device, &fragModInfo, 0, &fragShaderModule);
    if (res != VK_SUCCESS) { ExitProcess(17); }

    VkPipelineShaderStageCreateInfo shaderStages[2];
    memset(shaderStages, 0, sizeof(shaderStages));
    shaderStages[0].sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
    shaderStages[0].stage = VK_SHADER_STAGE_VERTEX_BIT;
    shaderStages[0].module = vertShaderModule;
    shaderStages[0].pName = "main";

    shaderStages[1].sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
    shaderStages[1].stage = VK_SHADER_STAGE_FRAGMENT_BIT;
    shaderStages[1].module = fragShaderModule;
    shaderStages[1].pName = "main";

    /* Vertex input binding & attribute */
    VkVertexInputBindingDescription bindingDesc;
    memset(&bindingDesc, 0, sizeof(bindingDesc));
    bindingDesc.binding = 0;
    bindingDesc.stride = 2 * sizeof(float);
    bindingDesc.inputRate = VK_VERTEX_INPUT_RATE_VERTEX;

    VkVertexInputAttributeDescription attribDesc;
    memset(&attribDesc, 0, sizeof(attribDesc));
    attribDesc.location = 0;
    attribDesc.binding = 0;
    attribDesc.format = VK_FORMAT_R32G32_SFLOAT;
    attribDesc.offset = 0;

    VkPipelineVertexInputStateCreateInfo vertexInputInfo;
    memset(&vertexInputInfo, 0, sizeof(vertexInputInfo));
    vertexInputInfo.sType = VK_STRUCTURE_TYPE_PIPELINE_VERTEX_INPUT_STATE_CREATE_INFO;
    vertexInputInfo.vertexBindingDescriptionCount = 1;
    vertexInputInfo.pVertexBindingDescriptions = &bindingDesc;
    vertexInputInfo.vertexAttributeDescriptionCount = 1;
    vertexInputInfo.pVertexAttributeDescriptions = &attribDesc;

    VkPipelineInputAssemblyStateCreateInfo inputAssembly;
    memset(&inputAssembly, 0, sizeof(inputAssembly));
    inputAssembly.sType = VK_STRUCTURE_TYPE_PIPELINE_INPUT_ASSEMBLY_STATE_CREATE_INFO;
    inputAssembly.topology = VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST;
    inputAssembly.primitiveRestartEnable = VK_FALSE;

    VkViewport viewport;
    viewport.x = 0.0f; viewport.y = 0.0f;
    viewport.width = (float)FB_WIDTH; viewport.height = (float)FB_HEIGHT;
    viewport.minDepth = 0.0f; viewport.maxDepth = 1.0f;

    VkRect2D scissor;
    scissor.offset.x = 0; scissor.offset.y = 0;
    scissor.extent.width = FB_WIDTH; scissor.extent.height = FB_HEIGHT;

    VkPipelineViewportStateCreateInfo viewportState;
    memset(&viewportState, 0, sizeof(viewportState));
    viewportState.sType = VK_STRUCTURE_TYPE_PIPELINE_VIEWPORT_STATE_CREATE_INFO;
    viewportState.viewportCount = 1;
    viewportState.pViewports = &viewport;
    viewportState.scissorCount = 1;
    viewportState.pScissors = &scissor;

    VkPipelineRasterizationStateCreateInfo rasterizer;
    memset(&rasterizer, 0, sizeof(rasterizer));
    rasterizer.sType = VK_STRUCTURE_TYPE_PIPELINE_RASTERIZATION_STATE_CREATE_INFO;
    rasterizer.polygonMode = VK_POLYGON_MODE_FILL;
    rasterizer.lineWidth = 1.0f;
    rasterizer.cullMode = VK_CULL_MODE_NONE;
    rasterizer.frontFace = VK_FRONT_FACE_COUNTER_CLOCKWISE;

    VkPipelineMultisampleStateCreateInfo multisampling;
    memset(&multisampling, 0, sizeof(multisampling));
    multisampling.sType = VK_STRUCTURE_TYPE_PIPELINE_MULTISAMPLE_STATE_CREATE_INFO;
    multisampling.rasterizationSamples = VK_SAMPLE_COUNT_1_BIT;

    VkPipelineColorBlendAttachmentState colorBlendAttachment;
    memset(&colorBlendAttachment, 0, sizeof(colorBlendAttachment));
    colorBlendAttachment.colorWriteMask = VK_COLOR_COMPONENT_R_BIT | VK_COLOR_COMPONENT_G_BIT | VK_COLOR_COMPONENT_B_BIT | VK_COLOR_COMPONENT_A_BIT;
    colorBlendAttachment.blendEnable = VK_FALSE;

    VkPipelineColorBlendStateCreateInfo colorBlending;
    memset(&colorBlending, 0, sizeof(colorBlending));
    colorBlending.sType = VK_STRUCTURE_TYPE_PIPELINE_COLOR_BLEND_STATE_CREATE_INFO;
    colorBlending.attachmentCount = 1;
    colorBlending.pAttachments = &colorBlendAttachment;

    VkPipelineLayoutCreateInfo pipelineLayoutInfo;
    memset(&pipelineLayoutInfo, 0, sizeof(pipelineLayoutInfo));
    pipelineLayoutInfo.sType = VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO;

    VkPipelineLayout pipelineLayout = 0;
    res = pvkCreatePipelineLayout(device, &pipelineLayoutInfo, 0, &pipelineLayout);
    if (res != VK_SUCCESS) { ExitProcess(17); }

    VkGraphicsPipelineCreateInfo pipelineInfo;
    memset(&pipelineInfo, 0, sizeof(pipelineInfo));
    pipelineInfo.sType = VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_CREATE_INFO;
    pipelineInfo.stageCount = 2;
    pipelineInfo.pStages = shaderStages;
    pipelineInfo.pVertexInputState = &vertexInputInfo;
    pipelineInfo.pInputAssemblyState = &inputAssembly;
    pipelineInfo.pViewportState = &viewportState;
    pipelineInfo.pRasterizationState = &rasterizer;
    pipelineInfo.pMultisampleState = &multisampling;
    pipelineInfo.pColorBlendState = &colorBlending;
    pipelineInfo.layout = pipelineLayout;
    pipelineInfo.renderPass = renderPass;
    pipelineInfo.subpass = 0;

    VkPipeline graphicsPipeline = 0;
    res = pvkCreateGraphicsPipelines(device, 0, 1, &pipelineInfo, 0, &graphicsPipeline);
    if (res != VK_SUCCESS) { ExitProcess(17); }
    print_str("[OFFSCREEN_VK] SUCCESS: Graphics pipeline created successfully.\n");

    /* Step 7: Vertex Buffer & Staging Buffer */
    print_str("[OFFSCREEN_VK] Step 7: Creating Vertex Buffer and Staging Buffer...\n");
    float vertices[6] = {
         0.0f, -0.6f,   /* Top */
         0.6f,  0.6f,   /* Bottom Right */
        -0.6f,  0.6f    /* Bottom Left */
    };

    uint64_t pipeline_end=bench_clock();
    VkBufferCreateInfo vbInfo;
    memset(&vbInfo, 0, sizeof(vbInfo));
    vbInfo.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO;
    vbInfo.size = sizeof(vertices);
    vbInfo.usage = VK_BUFFER_USAGE_VERTEX_BUFFER_BIT;
    vbInfo.sharingMode = VK_SHARING_MODE_EXCLUSIVE;

    VkBuffer vertexBuffer = 0;
    res = pvkCreateBuffer(device, &vbInfo, 0, &vertexBuffer);
    if (res != VK_SUCCESS) { ExitProcess(18); }

    VkMemoryRequirements vbMemReqs;
    pvkGetBufferMemoryRequirements(device, vertexBuffer, &vbMemReqs);

    VkMemoryAllocateInfo vbAllocInfo;
    memset(&vbAllocInfo, 0, sizeof(vbAllocInfo));
    vbAllocInfo.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO;
    vbAllocInfo.allocationSize = vbMemReqs.size;
    vbAllocInfo.memoryTypeIndex = find_memory_type(vbMemReqs.memoryTypeBits, VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);

    VkDeviceMemory vertexBufferMemory = 0;
    res = pvkAllocateMemory(device, &vbAllocInfo, 0, &vertexBufferMemory);
    if (res != VK_SUCCESS) { ExitProcess(18); }
    res = pvkBindBufferMemory(device, vertexBuffer, vertexBufferMemory, 0);
    if (res != VK_SUCCESS) { ExitProcess(18); }

    void* mappedVertices = 0;
    res = pvkMapMemory(device, vertexBufferMemory, 0, sizeof(vertices), 0, &mappedVertices);
    if (res != VK_SUCCESS || !mappedVertices) { ExitProcess(18); }
    memcpy(mappedVertices, vertices, sizeof(vertices));
    pvkUnmapMemory(device, vertexBufferMemory);

    /* Staging Buffer for readback */
    VkBufferCreateInfo sbInfo;
    memset(&sbInfo, 0, sizeof(sbInfo));
    sbInfo.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO;
    sbInfo.size = FB_SIZE;
    sbInfo.usage = VK_BUFFER_USAGE_TRANSFER_DST_BIT;
    sbInfo.sharingMode = VK_SHARING_MODE_EXCLUSIVE;

    VkBuffer stagingBuffer = 0;
    res = pvkCreateBuffer(device, &sbInfo, 0, &stagingBuffer);
    if (res != VK_SUCCESS) { ExitProcess(18); }

    VkMemoryRequirements sbMemReqs;
    pvkGetBufferMemoryRequirements(device, stagingBuffer, &sbMemReqs);

    VkMemoryAllocateInfo sbAllocInfo;
    memset(&sbAllocInfo, 0, sizeof(sbAllocInfo));
    sbAllocInfo.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO;
    sbAllocInfo.allocationSize = sbMemReqs.size;
    sbAllocInfo.memoryTypeIndex = find_memory_type(sbMemReqs.memoryTypeBits, VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT);

    VkDeviceMemory stagingBufferMemory = 0;
    res = pvkAllocateMemory(device, &sbAllocInfo, 0, &stagingBufferMemory);
    if (res != VK_SUCCESS) { ExitProcess(18); }
    res = pvkBindBufferMemory(device, stagingBuffer, stagingBufferMemory, 0);
    if (res != VK_SUCCESS) { ExitProcess(18); }

    /* Command Pool & Buffer */
    VkCommandPoolCreateInfo poolInfo;
    memset(&poolInfo, 0, sizeof(poolInfo));
    poolInfo.sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO;
    poolInfo.flags = VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT;
    poolInfo.queueFamilyIndex = graphicsQueueIndex;
    poolInfo.flags = VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT;

    VkCommandPool commandPool = 0;
    res = pvkCreateCommandPool(device, &poolInfo, 0, &commandPool);
    if (res != VK_SUCCESS) { ExitProcess(19); }

    VkCommandBufferAllocateInfo cmdAllocInfo;
    memset(&cmdAllocInfo, 0, sizeof(cmdAllocInfo));
    cmdAllocInfo.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO;
    cmdAllocInfo.commandPool = commandPool;
    cmdAllocInfo.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY;
    cmdAllocInfo.commandBufferCount = 1;

    VkCommandBuffer cmdBuffer = 0;
    res = pvkAllocateCommandBuffers(device, &cmdAllocInfo, &cmdBuffer);
    if (res != VK_SUCCESS) { ExitProcess(19); }

    /* Record Render Commands */

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
          if(g==1){
            for(unsigned q=0;q<FB_SIZE;q++)inproc_packet.pixels[q]=bench_snapshot[q];
            inproc_packet.width=FB_WIDTH;inproc_packet.height=FB_HEIGHT;inproc_packet.pitch=FB_WIDTH*4;inproc_packet.payload_bytes=FB_SIZE;inproc_packet.phase=1;inproc_packet.seq++;inproc_packet.ready=0x504958454c;
            /* Ordinary stdout write reaches the existing syscall safe point; no new hypercall. */
            inproc_packet.pixels[0]=(unsigned char)inproc_packet.seq; /* explicit CPU identity watermark */
            print_str("INPROC_FRAME_COMMIT seq=");bench_num(inproc_packet.seq);print_str("\n");
          }
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
    inproc_packet.phase=4;print_str("INPROC_FRAME_END\n");
    /* Step 11: Cleanup */
    print_str("[OFFSCREEN_VK] Cleaning up Vulkan resources...\n");
    pvkDestroyBuffer(device, stagingBuffer, 0);
    pvkFreeMemory(device, stagingBufferMemory, 0);
    pvkDestroyBuffer(device, vertexBuffer, 0);
    pvkFreeMemory(device, vertexBufferMemory, 0);
    pvkDestroyFence(device, fence, 0);
    pvkDestroyCommandPool(device, commandPool, 0);
    pvkDestroyPipeline(device, graphicsPipeline, 0);
    pvkDestroyPipelineLayout(device, pipelineLayout, 0);
    pvkDestroyShaderModule(device, fragShaderModule, 0);
    pvkDestroyShaderModule(device, vertShaderModule, 0);
    pvkDestroyFramebuffer(device, framebuffer, 0);
    pvkDestroyImageView(device, imageView, 0);
    pvkDestroyRenderPass(device, renderPass, 0);
    pvkDestroyImage(device, offscreenImage, 0);
    pvkFreeMemory(device, imageMemory, 0);
    pvkDestroyDevice(device, 0);
    pvkDestroyInstance(instance, 0);

    print_str("==========================================================\n");
    print_str("[OFFSCREEN_VK] FINAL_STATUS: WIN_ARM64_INPROC_FRAME_OK\n");
    print_str("==========================================================\n");

    ExitProcess(0);
    return 0;
}

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
 *     Exit 0: Full Success (WIN_X64_OFFSCREEN_OK)
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

#define FB_WIDTH 64
#define FB_HEIGHT 64
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
    VkCommandBufferBeginInfo beginInfo;
    memset(&beginInfo, 0, sizeof(beginInfo));
    beginInfo.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO;
    res = pvkBeginCommandBuffer(cmdBuffer, &beginInfo);
    if (res != VK_SUCCESS) { ExitProcess(19); }

    VkClearValue clearColor;
    clearColor.color.float32[0] = 0.0f;   /* R */
    clearColor.color.float32[1] = 0.0f;   /* G */
    clearColor.color.float32[2] = 0.5f;   /* B (Dark Blue: 0, 0, 128, 255) */
    clearColor.color.float32[3] = 1.0f;   /* A */

    VkRenderPassBeginInfo rpBeginInfo;
    memset(&rpBeginInfo, 0, sizeof(rpBeginInfo));
    rpBeginInfo.sType = VK_STRUCTURE_TYPE_RENDER_PASS_BEGIN_INFO;
    rpBeginInfo.renderPass = renderPass;
    rpBeginInfo.framebuffer = framebuffer;
    rpBeginInfo.renderArea.offset.x = 0;
    rpBeginInfo.renderArea.offset.y = 0;
    rpBeginInfo.renderArea.extent.width = FB_WIDTH;
    rpBeginInfo.renderArea.extent.height = FB_HEIGHT;
    rpBeginInfo.clearValueCount = 1;
    rpBeginInfo.pClearValues = &clearColor;

    pvkCmdBeginRenderPass(cmdBuffer, &rpBeginInfo, VK_SUBPASS_CONTENTS_INLINE);
    pvkCmdBindPipeline(cmdBuffer, VK_PIPELINE_BIND_POINT_GRAPHICS, graphicsPipeline);
    VkDeviceSize offsets[1] = {0};
    pvkCmdBindVertexBuffers(cmdBuffer, 0, 1, &vertexBuffer, offsets);

    if (!opt_skip_draw) {
        print_str("[OFFSCREEN_VK] Executing vkCmdDraw(vertexCount=3, instanceCount=1)...\n");
        pvkCmdDraw(cmdBuffer, 3, 1, 0, 0);
    } else {
        print_str("[OFFSCREEN_VK] [NEGATIVE TEST] Skipping vkCmdDraw!\n");
    }

    pvkCmdEndRenderPass(cmdBuffer);

    /* Transition image from COLOR_ATTACHMENT_OPTIMAL to TRANSFER_SRC_OPTIMAL */
    VkImageMemoryBarrier barrier;
    memset(&barrier, 0, sizeof(barrier));
    barrier.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER;
    barrier.oldLayout = VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL;
    barrier.newLayout = VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL;
    barrier.srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    barrier.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    barrier.image = offscreenImage;
    barrier.subresourceRange.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
    barrier.subresourceRange.baseMipLevel = 0;
    barrier.subresourceRange.levelCount = 1;
    barrier.subresourceRange.baseArrayLayer = 0;
    barrier.subresourceRange.layerCount = 1;
    barrier.srcAccessMask = VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT;
    barrier.dstAccessMask = VK_ACCESS_TRANSFER_READ_BIT;

    pvkCmdPipelineBarrier(cmdBuffer,
        VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT,
        VK_PIPELINE_STAGE_TRANSFER_BIT,
        0, 0, 0, 0, 0, 1, &barrier);

    /* Copy image to staging buffer */
    VkBufferImageCopy region;
    memset(&region, 0, sizeof(region));
    region.bufferOffset = 0;
    region.bufferRowLength = 0;
    region.bufferImageHeight = 0;
    region.imageSubresource.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
    region.imageSubresource.mipLevel = 0;
    region.imageSubresource.baseArrayLayer = 0;
    region.imageSubresource.layerCount = 1;
    region.imageOffset.x = 0; region.imageOffset.y = 0; region.imageOffset.z = 0;
    region.imageExtent.width = FB_WIDTH;
    region.imageExtent.height = FB_HEIGHT;
    region.imageExtent.depth = 1;

    pvkCmdCopyImageToBuffer(cmdBuffer, offscreenImage, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, stagingBuffer, 1, &region);
    res = pvkEndCommandBuffer(cmdBuffer);
    if (res != VK_SUCCESS) { ExitProcess(19); }

    /* Step 8: Submit Queue & Wait on Fence */
    print_str("[OFFSCREEN_VK] Step 8: Submitting queue and waiting on fence...\n");
    VkFenceCreateInfo fenceInfo;
    memset(&fenceInfo, 0, sizeof(fenceInfo));
    fenceInfo.sType = VK_STRUCTURE_TYPE_FENCE_CREATE_INFO;

    VkFence fence = 0;
    res = pvkCreateFence(device, &fenceInfo, 0, &fence);
    if (res != VK_SUCCESS) { ExitProcess(20); }

    VkSubmitInfo submitInfo;
    memset(&submitInfo, 0, sizeof(submitInfo));
    submitInfo.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
    submitInfo.commandBufferCount = 1;
    submitInfo.pCommandBuffers = &cmdBuffer;

    res = pvkQueueSubmit(graphicsQueue, 1, &submitInfo, fence);
    if (res != VK_SUCCESS) { ExitProcess(19); }

    /* Wait for fence with 10 second timeout */
    res = pvkWaitForFences(device, 1, &fence, VK_TRUE, 10000000000ULL);
    if (res != VK_SUCCESS) {
        print_str("[OFFSCREEN_VK] ERROR: vkWaitForFences failed or timed out! res=");
        print_int(res);
        print_str("\n");
        ExitProcess(20);
    }
    print_str("[OFFSCREEN_VK] SUCCESS: Render complete, fence signaled.\n");

    /* Step 9: Map Staging Buffer & Verify Pixels */
    print_str("[OFFSCREEN_VK] Step 9: Reading back staging buffer and verifying pixels...\n");
    unsigned char* pixels = 0;
    /* Map entire staging allocation to align mapped range with VK_WHOLE_SIZE invalidation */
    res = pvkMapMemory(device, stagingBufferMemory, 0, sbMemReqs.size, 0, (void**)&pixels);
    if (res != VK_SUCCESS || !pixels) {
        print_str("[OFFSCREEN_VK] ERROR: vkMapMemory failed! res=");
        print_int(res);
        print_str("\n");
        ExitProcess(20);
    }

    VkMappedMemoryRange range;
    memset(&range, 0, sizeof(range));
    range.sType = VK_STRUCTURE_TYPE_MAPPED_MEMORY_RANGE;
    range.memory = stagingBufferMemory;
    range.offset = 0;
    range.size = VK_WHOLE_SIZE;
    res = pvkInvalidateMappedMemoryRanges(device, 1, &range);
    if (res != VK_SUCCESS) {
        print_str("[OFFSCREEN_VK] ERROR: vkInvalidateMappedMemoryRanges failed! res=");
        print_int(res);
        print_str("\n");
        ExitProcess(20);
    }

    /* Expected colors */
    int exp_r = opt_bad_expect ? 0 : 255;
    int exp_g = 0;
    int exp_b = opt_bad_expect ? 255 : 0;
    int exp_a = 255;

    /* Sample interior triangle points:
     * (32, 38) centroid
     * (32, 25) top center
     * (22, 44) bottom left
     * (42, 44) bottom right
     */
    int interior_points[4][2] = {
        {32, 38},
        {32, 25},
        {22, 44},
        {42, 44}
    };

    for (int p = 0; p < 4; p++) {
        int x = interior_points[p][0];
        int y = interior_points[p][1];
        int idx = (y * FB_WIDTH + x) * FB_CHANNELS;
        unsigned char r = pixels[idx + 0];
        unsigned char g = pixels[idx + 1];
        unsigned char b = pixels[idx + 2];
        unsigned char a = pixels[idx + 3];

        print_str("  [INTERIOR (");
        print_uint(x); print_str(","); print_uint(y);
        print_str(")] Observed: R="); print_uint(r);
        print_str(" G="); print_uint(g);
        print_str(" B="); print_uint(b);
        print_str(" A="); print_uint(a);

        /* Triangle is Red: 255, 0, 0, 255 */
        if (r < 240 || g > 15 || b > 15 || a < 240) {
            print_str(" -> MISMATCH! Expected Triangle Color\n");
            ExitProcess(21);
        } else {
            print_str(" -> MATCH (Triangle)\n");
        }
    }

    /* Sample exterior background points (away from boundaries):
     * (5, 5) top left
     * (58, 5) top right
     * (5, 58) bottom left
     * (58, 58) bottom right
     */
    int exterior_points[4][2] = {
        {5, 5},
        {58, 5},
        {5, 58},
        {58, 58}
    };

    for (int p = 0; p < 4; p++) {
        int x = exterior_points[p][0];
        int y = exterior_points[p][1];
        int idx = (y * FB_WIDTH + x) * FB_CHANNELS;
        unsigned char r = pixels[idx + 0];
        unsigned char g = pixels[idx + 1];
        unsigned char b = pixels[idx + 2];
        unsigned char a = pixels[idx + 3];

        print_str("  [EXTERIOR (");
        print_uint(x); print_str(","); print_uint(y);
        print_str(")] Observed: R="); print_uint(r);
        print_str(" G="); print_uint(g);
        print_str(" B="); print_uint(b);
        print_str(" A="); print_uint(a);

        /* Clear color is Dark Blue: 0, 0, 128, 255 */
        if (r > 15 || g > 15 || b < 115 || b > 140 || a < 240) {
            print_str(" -> MISMATCH! Expected Clear Background Color\n");
            ExitProcess(22);
        } else {
            print_str(" -> MATCH (Background)\n");
        }
    }

    print_str("[OFFSCREEN_VK] SUCCESS: All interior and exterior pixel assertions passed!\n");

    /* Step 10: Write raw framebuffer file */
    print_str("[OFFSCREEN_VK] Step 10: Saving framebuffer to C:\\framebuffer.raw...\n");
    HANDLE hFile = CreateFileA("C:\\framebuffer.raw", GENERIC_WRITE, 0, 0, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, 0);
    if (hFile == (HANDLE)-1) {
        print_str("[OFFSCREEN_VK] ERROR: CreateFileA failed! Error=");
        print_uint(GetLastError());
        print_str("\n");
        ExitProcess(23);
    }
    DWORD wrote = 0;
    int ok = WriteFile(hFile, pixels, FB_SIZE, &wrote, 0);
    CloseHandle(hFile);
    if (!ok || wrote != FB_SIZE) {
        print_str("[OFFSCREEN_VK] ERROR: WriteFile failed! ok=");
        print_int(ok);
        print_str(" wrote=");
        print_uint(wrote);
        print_str(" expected=");
        print_uint(FB_SIZE);
        print_str("\n");
        ExitProcess(23);
    }
    print_str("[OFFSCREEN_VK] SUCCESS: 16384 bytes written to C:\\framebuffer.raw\n");

    pvkUnmapMemory(device, stagingBufferMemory);

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
    print_str("[OFFSCREEN_VK] FINAL_STATUS: WIN_X64_OFFSCREEN_OK\n");
    print_str("==========================================================\n");

    ExitProcess(0);
    return 0;
}

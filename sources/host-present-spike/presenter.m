#import <AppKit/AppKit.h>
#import <QuartzCore/QuartzCore.h>
#import <mach/mach_time.h>
#include <stdio.h>
#include <math.h>
static uint64_t now_ns(void) {
    mach_timebase_info_data_t info;mach_timebase_info(&info);
    return (uint64_t)((__uint128_t)mach_absolute_time()*info.numer/info.denom);
}
static void log_stage(NSString *stage) {printf("HOST_PRESENT stage=%s monotonic_ns=%llu\n",stage.UTF8String,(unsigned long long)now_ns());fflush(stdout);}
static void pump(double duration) {
    NSDate *end=[NSDate dateWithTimeIntervalSinceNow:duration];
    while(end.timeIntervalSinceNow>0) {
        NSEvent *e=[NSApp nextEventMatchingMask:NSEventMaskAny untilDate:[NSDate dateWithTimeIntervalSinceNow:0.005] inMode:NSDefaultRunLoopMode dequeue:YES];
        if(e)[NSApp sendEvent:e];
        [NSApp updateWindows];
    }
}
static int fail(NSString *message) {fprintf(stderr,"HOST_PRESENT_FAIL %s\n",message.UTF8String);return 2;}
int main(int argc,const char **argv) {
 @autoreleasepool {
    if(argc==4 && !strcmp(argv[1],"--publish")) {
        NSString *target=[NSString stringWithUTF8String:argv[2]];
        NSString *sourcePath=[NSString stringWithUTF8String:argv[3]];
        uint64_t begin=now_ns();NSError *publishError=nil;
        NSData *frame=[NSData dataWithContentsOfFile:sourcePath];
        if(frame.length!=16384)return fail(@"publisher source length");
        NSString *tmp=[target stringByAppendingPathComponent:@"frame.rgba.tmp"];
        if(![frame writeToFile:tmp options:0 error:&publishError])return fail(@"publisher frame write");
        if(rename(tmp.fileSystemRepresentation,[[target stringByAppendingPathComponent:@"frame.rgba"] fileSystemRepresentation]))return fail(@"frame atomic rename");
        NSDictionary *marker=@{@"width":@64,@"height":@64,@"pitch":@256,@"format":@"RGBA8",
             @"copy_begin_ns":@(begin),@"publish_ns":@(now_ns())};
        NSData *data=[NSJSONSerialization dataWithJSONObject:marker options:NSJSONWritingPrettyPrinted error:&publishError];
        NSString *markerTmp=[target stringByAppendingPathComponent:@"frame.ready.json.tmp"];
        if(![data writeToFile:markerTmp options:0 error:&publishError])return fail(@"marker write");
        if(rename(markerTmp.fileSystemRepresentation,[[target stringByAppendingPathComponent:@"frame.ready.json"] fileSystemRepresentation]))return fail(@"marker atomic rename");
        log_stage(@"PUBLISHED");return 0;
    }
    if(argc!=2)return fail(@"usage: presenter HANDOFF_DIR");
    NSString *dir=[NSString stringWithUTF8String:argv[1]];
    NSString *ready=[dir stringByAppendingPathComponent:@"frame.ready.json"];
    log_stage(@"PROCESS_BEGIN");
    [NSApplication sharedApplication];[NSApp setActivationPolicy:NSApplicationActivationPolicyRegular];[NSApp finishLaunching];
    log_stage(@"HELPER_READY");
    uint64_t limit=now_ns()+10000000000ULL;
    while(![[NSFileManager defaultManager] fileExistsAtPath:ready]) {
        if(now_ns()>limit)return fail(@"handoff timeout");pump(0.005);
    }
    uint64_t receive=now_ns();log_stage(@"RECEIVE");
    NSData *metaData=[NSData dataWithContentsOfFile:ready];NSError *error=nil;
    NSDictionary *meta=[NSJSONSerialization JSONObjectWithData:metaData options:0 error:&error];
    if(!meta || [meta[@"width"] intValue]!=64 || [meta[@"height"] intValue]!=64 || [meta[@"pitch"] intValue]!=256)
        return fail(@"bad frame metadata");
    NSData *raw=[NSData dataWithContentsOfFile:[dir stringByAppendingPathComponent:@"frame.rgba"]];
    if(raw.length!=16384)return fail(@"bad raw length");
    NSBitmapImageRep *source=[[NSBitmapImageRep alloc] initWithBitmapDataPlanes:NULL pixelsWide:64 pixelsHigh:64 bitsPerSample:8 samplesPerPixel:4 hasAlpha:YES isPlanar:NO colorSpaceName:NSDeviceRGBColorSpace bitmapFormat:NSBitmapFormatAlphaNonpremultiplied bytesPerRow:256 bitsPerPixel:32];
    if(!source)return fail(@"source bitmap allocation");
    memcpy(source.bitmapData,raw.bytes,raw.length);
    source=[source bitmapImageRepByRetaggingWithColorSpace:NSColorSpace.sRGBColorSpace];
    NSScreen *screen=NSScreen.mainScreen;if(!screen)return fail(@"no active host screen");
    double scale=screen.backingScaleFactor;
    if(scale<1 || scale>4)return fail(@"unsupported backing scale");
    NSSize points=NSMakeSize(64.0/scale,64.0/scale);
    NSWindow *window=[[NSWindow alloc] initWithContentRect:NSMakeRect(180,180,points.width,points.height) styleMask:NSWindowStyleMaskTitled|NSWindowStyleMaskClosable backing:NSBackingStoreBuffered defer:NO screen:screen];
    window.title=@"Guest framebuffer — host-only presentation spike";
    window.colorSpace=NSColorSpace.sRGBColorSpace;window.releasedWhenClosed=NO;
    NSImage *image=[[NSImage alloc] initWithSize:points];source.size=points;[image addRepresentation:source];
    NSImageView *view=[[NSImageView alloc] initWithFrame:NSMakeRect(0,0,points.width,points.height)];
    view.image=image;view.imageScaling=NSImageScaleNone;view.imageAlignment=NSImageAlignTopLeft;view.wantsLayer=YES;
    view.layer.minificationFilter=kCAFilterNearest;view.layer.magnificationFilter=kCAFilterNearest;
    window.contentView=view;[window makeKeyAndOrderFront:nil];[NSApp activateIgnoringOtherApps:YES];
    [view setNeedsDisplay:YES];[view displayIfNeeded];[CATransaction flush];
    uint64_t commit=now_ns();log_stage(@"COMMIT");pump(0.15);
    NSRect backing=[view convertRectToBacking:view.bounds];
    NSBitmapImageRep *capture=[view bitmapImageRepForCachingDisplayInRect:view.bounds];
    if(!capture)return fail(@"view capture unavailable; pixels UNKNOWN");
    [view cacheDisplayInRect:view.bounds toBitmapImageRep:capture];
    uint64_t captured=now_ns();log_stage(@"VIEW_CAPTURED");
    NSData *png=[capture representationUsingType:NSBitmapImageFileTypePNG properties:@{}];
    if(!png || ![png writeToFile:[dir stringByAppendingPathComponent:@"host-view.png"] options:NSDataWritingAtomic error:&error])
        return fail(@"PNG save failure");
    NSInteger width=capture.pixelsWide,height=capture.pixelsHigh;
    NSMutableData *normalized=[NSMutableData dataWithLength:width*height*4];unsigned char *bytes=normalized.mutableBytes;
    for(NSInteger y=0;y<height;y++)for(NSInteger x=0;x<width;x++){
        NSUInteger sample[4]={0,0,0,0};
        [capture getPixel:sample atX:x y:y];
        for(int k=0;k<4;k++)bytes[(y*width+x)*4+k]=(unsigned char)sample[k];
    }
    if(![normalized writeToFile:[dir stringByAppendingPathComponent:@"host-view.rgba"] options:NSDataWritingAtomic error:&error])return fail(@"raw capture save failure");
    NSDictionary *result=@{@"receive_ns":@(receive),@"commit_ns":@(commit),@"capture_ns":@(captured),
        @"publish_ns":meta[@"publish_ns"],@"copy_begin_ns":meta[@"copy_begin_ns"],@"clock":@"mach_absolute_time scaled with mach_timebase_info in publisher and viewer",@"width":@(width),@"height":@(height),
        @"capture_color_space":capture.colorSpace.localizedName,@"capture_samples_per_pixel":@(capture.samplesPerPixel),@"capture_bits_per_sample":@(capture.bitsPerSample),@"backing_scale":@(scale),@"content_width_points":@(points.width),@"content_height_points":@(points.height),
        @"backing_width":@(backing.size.width),@"backing_height":@(backing.size.height),
        @"window_number":@(window.windowNumber),@"is_visible":@(window.isVisible),@"occlusion_visible":@((window.occlusionState&NSWindowOcclusionStateVisible)!=0),
        @"on_active_space":@(window.onActiveSpace),@"screenshot_method":@"NSView bitmapImageRepForCachingDisplayInRect/cacheDisplayInRect; not system screen capture",
        @"receive_to_commit_ms":@((commit-receive)/1e6),@"receive_to_capture_ms":@((captured-receive)/1e6),
        @"publish_to_capture_ms":@((captured-[meta[@"publish_ns"] unsignedLongLongValue])/1e6),
        @"one_frame_bytes":@(raw.length),@"frame_count":@1,
        @"window_management_integration":@"UNKNOWN",@"input_roundtrip":@"UNKNOWN"};
    NSData *json=[NSJSONSerialization dataWithJSONObject:result options:NSJSONWritingPrettyPrinted error:&error];
    if(!json || ![json writeToFile:[dir stringByAppendingPathComponent:@"host-result.json"] options:NSDataWritingAtomic error:&error])return fail(@"result save failure");
    printf("HOST_WINDOW number=%ld visible=%d occlusion_visible=%d active_space=%d capture=%ldx%ld scale=%.1f\n",(long)window.windowNumber,window.isVisible,(window.occlusionState&NSWindowOcclusionStateVisible)!=0,window.onActiveSpace,(long)width,(long)height,scale);fflush(stdout);
    pump(1.5);[window close];log_stage(@"WINDOW_CLOSED");return 0;
 }
}

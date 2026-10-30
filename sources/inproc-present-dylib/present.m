#import <AppKit/AppKit.h>
#import <QuartzCore/QuartzCore.h>
#import <mach/mach_time.h>
#include <pthread.h>
#include <stdio.h>
#include <unistd.h>
#include <stdlib.h>
struct Packet {uint64_t ready,seq,phase;unsigned char pixels[16384];};
static NSWindow *window;static NSImageView *view;static uint64_t last,previous_phase,updates,active_entries,active_begin,active_last;
static uint64_t ns(void){mach_timebase_info_data_t t;mach_timebase_info(&t);return (uint64_t)((__uint128_t)mach_absolute_time()*t.numer/t.denom);}
static void die(const char *s){fprintf(stderr,"INPROC_FAIL %s\n",s);_exit(87);}
static NSString *outpath(NSString *name){const char *d=getenv("ELFUSE_INPROC_PRESENT_OUT");if(!d)die("output_config");return [[NSString stringWithUTF8String:d] stringByAppendingPathComponent:name];}
__attribute__((visibility("default"))) void inproc_present_tick(const void *ptr,size_t length){
 @autoreleasepool {
  if(!pthread_main_np())die("AppKit_callback_not_main");
  long width=getenv("ELFUSE_INPROC_PRESENT_WIDTH")?atol(getenv("ELFUSE_INPROC_PRESENT_WIDTH")):64;
  long height=getenv("ELFUSE_INPROC_PRESENT_HEIGHT")?atol(getenv("ELFUSE_INPROC_PRESENT_HEIGHT")):64;
  if(width<1||width>1920||height<1||height>1080||length!=(size_t)width*height*4+(getenv("ELFUSE_INPROC_PRESENT_FRAME_LAYOUT")?56:24))die("packet_size");
  size_t pixel_bytes=(size_t)width*height*4;
  const volatile struct Packet *p=ptr;if(p->ready!=0x504958454c)return;
  const void *pixel_ptr=(const unsigned char*)ptr+24;
  if(getenv("ELFUSE_INPROC_PRESENT_FRAME_LAYOUT")){
   const uint64_t *meta=(const uint64_t*)ptr;
   if(meta[3]!=(uint64_t)width || meta[4]!=(uint64_t)height || meta[5]!=(uint64_t)width*4 || meta[6]!=pixel_bytes)die("dimensions_payload_mismatch");
   pixel_ptr=(const unsigned char*)ptr+56;
  }
  uint64_t begin=ns(),phase=p->phase,seq=p->seq;
  if(phase!=4){active_entries++;if(!active_begin)active_begin=begin;active_last=begin;}
  if(phase==4){
   fprintf(stderr,"INPROC_ACTIVE pid=%d entries=%llu first_ns=%llu last_ns=%llu\n",getpid(),(unsigned long long)active_entries,(unsigned long long)active_begin,(unsigned long long)active_last);
   fprintf(stderr,"INPROC_CLOSE updates=%llu main=%d\n",(unsigned long long)updates,pthread_main_np());
   [window close];window=nil;view=nil;return;
  }
  static uint64_t deferred_seq;
  if(last && begin-last<16000000 && phase==previous_phase){if(seq!=deferred_seq){fprintf(stderr,"INPROC_DEFER seq=%llu reason=16ms_throttle elapsed_ns=%llu\n",(unsigned long long)seq,(unsigned long long)(begin-last));deferred_seq=seq;}return;}
  if(!window){
   [NSApplication sharedApplication];[NSApp setActivationPolicy:NSApplicationActivationPolicyRegular];[NSApp finishLaunching];
   NSScreen *screen=NSScreen.mainScreen;if(!screen)die("no_screen");double scale=screen.backingScaleFactor;
   NSSize size=NSMakeSize(width/scale,height/scale);
   window=[[NSWindow alloc] initWithContentRect:NSMakeRect(180,180,size.width,size.height) styleMask:NSWindowStyleMaskTitled|NSWindowStyleMaskClosable backing:NSBackingStoreBuffered defer:NO screen:screen];
   window.releasedWhenClosed=NO;window.title=@"elfuse in-process guest buffer spike";window.colorSpace=NSColorSpace.sRGBColorSpace;
   view=[[NSImageView alloc] initWithFrame:NSMakeRect(0,0,size.width,size.height)];view.imageScaling=NSImageScaleNone;window.contentView=view;
   [window makeKeyAndOrderFront:nil];[NSApp activateIgnoringOtherApps:YES];
  }
  NSBitmapImageRep *bitmap=[[NSBitmapImageRep alloc] initWithBitmapDataPlanes:NULL pixelsWide:width pixelsHigh:height bitsPerSample:8 samplesPerPixel:4 hasAlpha:YES isPlanar:NO colorSpaceName:NSDeviceRGBColorSpace bitmapFormat:NSBitmapFormatAlphaNonpremultiplied bytesPerRow:width*4 bitsPerPixel:32];
  /* Direct borrowed guest backing read; local bitmap copy is explicit, not exported IPC. */
  memcpy(bitmap.bitmapData,pixel_ptr,pixel_bytes);
  bitmap=[bitmap bitmapImageRepByRetaggingWithColorSpace:NSColorSpace.sRGBColorSpace];bitmap.size=view.bounds.size;
  NSImage *image=[[NSImage alloc] initWithSize:view.bounds.size];[image addRepresentation:bitmap];view.image=image;
  [view setNeedsDisplay:YES];[view displayIfNeeded];[CATransaction flush];
  NSEvent *e;unsigned events=0;while(events<8 && (e=[NSApp nextEventMatchingMask:NSEventMaskAny untilDate:[NSDate distantPast] inMode:NSDefaultRunLoopMode dequeue:YES])){[NSApp sendEvent:e];events++;}
  [NSApp updateWindows];
  /* Deliberately bounded UI settling; measured as guest-blocking callback time. */
  if(!updates){
   uint64_t until=ns()+150000000;
   while(ns()<until){NSEvent *pending=[NSApp nextEventMatchingMask:NSEventMaskAny untilDate:[NSDate dateWithTimeIntervalSinceNow:0.005] inMode:NSDefaultRunLoopMode dequeue:YES];if(pending)[NSApp sendEvent:pending];[NSApp updateWindows];}
  }
  if(!updates||phase!=previous_phase){
   NSBitmapImageRep *capture=[view bitmapImageRepForCachingDisplayInRect:view.bounds];if(!capture)die("capture_unavailable");
   [view cacheDisplayInRect:view.bounds toBitmapImageRep:capture];
   if(capture.pixelsWide!=width||capture.pixelsHigh!=height)die("capture_not_native_64x64");
   NSMutableData *raw=[NSMutableData dataWithLength:pixel_bytes];unsigned char *bytes=raw.mutableBytes;
   for(int y=0;y<height;y++)for(int x=0;x<width;x++){NSUInteger sample[4];[capture getPixel:sample atX:x y:y];for(int k=0;k<4;k++)bytes[(y*width+x)*4+k]=sample[k];}
   NSString *tag=[NSString stringWithFormat:@"phase%llu",(unsigned long long)phase];
   [raw writeToFile:outpath([tag stringByAppendingString:@".rgba"]) atomically:YES];
   [[capture representationUsingType:NSBitmapImageFileTypePNG properties:@{}] writeToFile:outpath([tag stringByAppendingString:@".png"]) atomically:YES];
   [[NSData dataWithBytes:pixel_ptr length:pixel_bytes] writeToFile:outpath([tag stringByAppendingString:@"-guest-direct.rgba"]) atomically:YES];
   fprintf(stderr,"INPROC_WINDOW phase=%llu number=%ld visible=%d occlusion=%d main=%d backing=%p guest_direct=%p seq=%llu pid=%d\n",(unsigned long long)phase,(long)window.windowNumber,window.isVisible,(window.occlusionState&NSWindowOcclusionStateVisible)!=0,pthread_main_np(),ptr,pixel_ptr,(unsigned long long)seq,getpid());
  }
  uint64_t end=ns();fprintf(stderr,"INPROC_UPDATE phase=%llu seq=%llu begin_ns=%llu duration_ns=%llu gap_ns=%llu events=%u pid=%d\n",(unsigned long long)phase,(unsigned long long)seq,(unsigned long long)begin,(unsigned long long)(end-begin),(unsigned long long)(last?begin-last:0),events,getpid());
  last=begin;previous_phase=phase;updates++;
 }
}

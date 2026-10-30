#import <AppKit/AppKit.h>
#import <QuartzCore/QuartzCore.h>
#import <mach/mach_time.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>
#include <signal.h>
#include <zlib.h>

static uint64_t nowNS(void) {
    mach_timebase_info_data_t t; mach_timebase_info(&t);
    return (uint64_t)((__uint128_t)mach_absolute_time()*t.numer/t.denom);
}
static void logJSON(NSDictionary *obj) {
    @synchronized([NSApplication class]) {
        NSData *d=[NSJSONSerialization dataWithJSONObject:obj options:0 error:NULL];
        fwrite(d.bytes,1,d.length,stdout); fputc('\n',stdout); fflush(stdout);
    }
}
static int peer=-1, listener=-1;
static NSLock *stateLock, *sendLock;
static NSMutableDictionary *slots[2];
static uint64_t generation=0,lastSeq=0;
static NSInteger width=0,height=0;
static BOOL configured=NO,stopping=NO;
static NSWindow *window;
static NSImageView *view;
static BOOL exactRead(int fd, void *out, size_t n) {
    size_t off=0; while(off<n) { ssize_t r=read(fd,(char*)out+off,n-off); if(r<=0)return NO;off+=r; } return YES;
}
static BOOL exactWrite(int fd,const void *p,size_t n) {
    size_t off=0;while(off<n){ssize_t r=write(fd,(const char*)p+off,n-off);if(r<=0)return NO;off+=r;}return YES;
}
static void ack(NSDictionary *fields) {
    NSMutableDictionary *h=[fields mutableCopy];h[@"v"]=@1;
    if(!h[@"type"])h[@"type"]=@"ACK";
    NSData *j=[NSJSONSerialization dataWithJSONObject:h options:0 error:NULL];
    uint32_t total=htonl((uint32_t)j.length+4), jl=htonl((uint32_t)j.length);
    [sendLock lock]; BOOL ok=exactWrite(peer,&total,4)&&exactWrite(peer,&jl,4)&&exactWrite(peer,j.bytes,j.length);[sendLock unlock];
    if(!ok)shutdown(peer,SHUT_RDWR);
    logJSON(h);
}
static void stopHost(NSString *reason) {
    if(stopping)return; stopping=YES;
    logJSON(@{@"event":@"stop",@"reason":reason,@"host_ns":@(nowNS())});
    if(peer>=0)shutdown(peer,SHUT_RDWR);
    if(listener>=0)shutdown(listener,SHUT_RDWR);
    [NSApp stop:nil];
    NSEvent *wake=[NSEvent otherEventWithType:NSEventTypeApplicationDefined location:NSZeroPoint modifierFlags:0 timestamp:0 windowNumber:0 context:nil subtype:0 data1:0 data2:0];
    [NSApp postEvent:wake atStart:NO];
}
static void terminal(NSMutableDictionary *slot,NSString *disposition) {
    NSDictionary *h=slot[@"header"];
    NSMutableDictionary *a=[@{@"ack_for":@"FRAME",@"stage":@"CONSUMED",@"sid":@1,@"gen":h[@"gen"],@"seq":h[@"seq"],@"slot":slot[@"index"],@"crc32":h[@"crc32"],@"disposition":disposition,@"host_ns":@(nowNS()),@"host_age_ms":@((nowNS()-[slot[@"received_ns"] unsignedLongLongValue])/1e6)} mutableCopy];
    if(slot[@"capture_crc32"]) {a[@"capture_crc32"]=slot[@"capture_crc32"];a[@"capture_match"]=slot[@"capture_match"];a[@"capture_domain"]=@"NSView cacheDisplay normalized RGBA8 opaque sRGB; not screen";}
    ack(a);
}
static BOOL positive(NSDictionary *h,NSString *key,uint64_t *out) {
    id value=h[key];if(![value isKindOfClass:[NSNumber class]])return NO;
    const char *t=[value objCType];if(CFGetTypeID((__bridge CFTypeRef)value)==CFBooleanGetTypeID() || strchr("fd",t[0]))return NO;
    long long n=[value longLongValue];if(n<=0)return NO;*out=(uint64_t)n;return YES;
}
static BOOL shape(NSDictionary *h,NSInteger *w,NSInteger *hh) {
    uint64_t a,b,p;if(!positive(h,@"w",&a)||!positive(h,@"h",&b)||!positive(h,@"pitch",&p))return NO;
    if(a>4096||b>4096||p!=a*4||a*b*4>16700000||![h[@"format"] isEqual:@"RGBA8"])return NO;
    *w=(NSInteger)a;*hh=(NSInteger)b;return YES;
}
static void consume(void) {
    [stateLock lock]; NSMutableDictionary *slot=nil;
    for(int i=0;i<2;i++)if([slots[i][@"state"] isEqual:@"READY"]){slot=slots[i];slot[@"state"]=@"READING";break;}
    [stateLock unlock];if(!slot)return;
    NSDictionary *h=slot[@"header"];NSData *raw=slot[@"payload"];
    NSBitmapImageRep *rep=[[NSBitmapImageRep alloc] initWithBitmapDataPlanes:NULL pixelsWide:width pixelsHigh:height bitsPerSample:8 samplesPerPixel:4 hasAlpha:YES isPlanar:NO colorSpaceName:NSDeviceRGBColorSpace bitmapFormat:NSBitmapFormatAlphaNonpremultiplied bytesPerRow:width*4 bitsPerPixel:32];
    memcpy(rep.bitmapData,raw.bytes,raw.length);
    rep=[rep bitmapImageRepByRetaggingWithColorSpace:NSColorSpace.sRGBColorSpace];
    NSSize points=view.bounds.size;rep.size=points;
    NSImage *image=[[NSImage alloc] initWithSize:points];[image addRepresentation:rep];view.image=image;
    [view setNeedsDisplay:YES];[view displayIfNeeded];[CATransaction flush];
    if([h[@"capture"] boolValue]) {
        NSBitmapImageRep *capture=[view bitmapImageRepForCachingDisplayInRect:view.bounds];
        [view cacheDisplayInRect:view.bounds toBitmapImageRep:capture];
        NSMutableData *normalized=[NSMutableData dataWithLength:width*height*4];unsigned char *dst=normalized.mutableBytes;
        BOOL sizeOK=capture.pixelsWide==width&&capture.pixelsHigh==height;
        if(sizeOK)for(NSInteger y=0;y<height;y++)for(NSInteger x=0;x<width;x++) {
            NSUInteger px[4]={0,0,0,255};[capture getPixel:px atX:x y:y];
            for(int k=0;k<4;k++)dst[(y*width+x)*4+k]=(unsigned char)px[k];
        }
        uint32_t crc=(uint32_t)crc32(0,dst,(uInt)normalized.length);
        slot[@"capture_crc32"]=@(crc);slot[@"capture_match"]=@(sizeOK&&[normalized isEqualToData:raw]);
        if(![slot[@"capture_match"] boolValue])logJSON(@{@"event":@"capture_mismatch",@"seq":h[@"seq"],@"width":@(capture.pixelsWide),@"height":@(capture.pixelsHigh),@"color_space":capture.colorSpace.localizedName?:@"unknown"});
    }
    terminal(slot,@"displayed");
    [stateLock lock];int index=[slot[@"index"] intValue];slots[index]=nil;[stateLock unlock];
}
@interface LabApp : NSApplication @end
@implementation LabApp
- (void)sendEvent:(NSEvent *)event {
    if(event.type==NSEventTypeApplicationDefined && event.subtype>0) {
        uint64_t handled=nowNS();
        logJSON(@{@"event":event.subtype==2?@"close_event":@"ui_event",@"host_ns":@(handled),@"main_thread":@([NSThread isMainThread])});
        ack(@{@"ack_for":@"EVENT",@"stage":@"HANDLED",@"event":event.subtype==2?@"close_event":@"ui_event",@"host_ns":@(handled)});
        if(event.subtype==2)[window performClose:nil];
    } else [super sendEvent:event];
}
@end
@interface Delegate : NSObject <NSWindowDelegate> @end
@implementation Delegate
- (BOOL)windowShouldClose:(id)sender { stopHost(@"window_close"); return YES; }
@end
static void configureWindow(NSInteger w,NSInteger h) {
    CGFloat scale=NSScreen.mainScreen.backingScaleFactor;
    NSSize points=NSMakeSize(w/scale,h/scale);
    [window setContentSize:points];view.frame=NSMakeRect(0,0,points.width,points.height);
}
static void reader(void) {
    @autoreleasepool {
    peer=accept(listener,NULL,NULL);if(peer<0){dispatch_async(dispatch_get_main_queue(),^{stopHost(@"accept_error");});return;}
    int noSig=1;setsockopt(peer,SOL_SOCKET,SO_NOSIGPIPE,&noSig,sizeof(noSig));
    struct timeval timeout={0,200000};setsockopt(peer,SOL_SOCKET,SO_SNDTIMEO,&timeout,sizeof(timeout));
    NSString *reason=@"eof";BOOL failure=NO;
    while(!stopping) {@autoreleasepool {
        uint32_t be=0;ssize_t r=read(peer,&be,4);
        if(r==0)break;
        if(r<0){reason=@"read_error";break;}
        if(r<4&&!exactRead(peer,((char*)&be)+r,4-r)){failure=YES;reason=@"short_length";break;}
        uint32_t total=ntohl(be),jbe;
        if(total<4||total>16777216){failure=YES;reason=@"packet_length";break;}
        if(!exactRead(peer,&jbe,4)){failure=YES;reason=@"short_json_length";break;}
        uint32_t jl=ntohl(jbe);
        if(jl<2||jl>65536||jl>total-4){failure=YES;reason=@"json_length";break;}
        NSMutableData *j=[NSMutableData dataWithLength:jl];
        if(!exactRead(peer,j.mutableBytes,jl)){failure=YES;reason=@"short_json";break;}
        id h=[NSJSONSerialization JSONObjectWithData:j options:0 error:NULL];
        if(![h isKindOfClass:[NSDictionary class]]){failure=YES;reason=@"json_object";break;}
        uint64_t v,sid;
        if(!positive(h,@"v",&v)||v!=1||!positive(h,@"sid",&sid)||sid!=1){failure=YES;reason=@"identity";break;}
        NSString *type=h[@"type"];
        BOOL flagsOK=YES;
        for(NSString *flag in @[@"capture",@"close"]) {
            id value=h[flag];
            if(value && (![value isKindOfClass:[NSNumber class]] || CFGetTypeID((__bridge CFTypeRef)value)!=CFBooleanGetTypeID()))flagsOK=NO;
        }
        if(![type isKindOfClass:[NSString class]]||!flagsOK){failure=YES;reason=@"field_types";break;}
        NSUInteger payloadLen=total-4-jl;
        if(![type isEqual:@"FRAME"]&&payloadLen){failure=YES;reason=@"control_payload";break;}
        if([type isEqual:@"CREATE"]||[type isEqual:@"RESIZE"]) {
            uint64_t gen;NSInteger w,hh;
            if(!positive(h,@"gen",&gen)||!shape(h,&w,&hh)||([type isEqual:@"CREATE"]?(configured||gen!=1):(!configured||gen<=generation))){failure=YES;reason=@"config_shape_generation";break;}
            dispatch_sync(dispatch_get_main_queue(),^{
                [stateLock lock];for(int i=0;i<2;i++)if(slots[i]){terminal(slots[i],@"invalidated");slots[i]=nil;}[stateLock unlock];
                width=w;height=hh;generation=gen;configured=YES;configureWindow(w,hh);
            });
            ack(@{@"ack_for":type,@"stage":@"CONFIGURED",@"sid":@1,@"gen":@(generation)});
        } else if([type isEqual:@"FRAME"]) {
            uint64_t gen,seq,bytes,crc;NSInteger w,hh;
            // crc32 zero is legal; other numeric fields must be positive.
            id c=h[@"crc32"];BOOL crcOK=NO;crc=0;
            if([c isKindOfClass:[NSNumber class]] && CFGetTypeID((__bridge CFTypeRef)c)!=CFBooleanGetTypeID()) {
                const char *ct=[c objCType];
                if(!strchr("fd",ct[0]) && [c longLongValue]>=0 && [c unsignedLongLongValue]<=UINT32_MAX) {
                    crcOK=YES;crc=[c unsignedLongLongValue];
                }
            }
            if(!configured||!positive(h,@"gen",&gen)||gen!=generation||!positive(h,@"seq",&seq)||seq<=lastSeq||!shape(h,&w,&hh)||w!=width||hh!=height||!positive(h,@"payload_bytes",&bytes)||bytes!=(uint64_t)w*hh*4||bytes!=payloadLen||!crcOK){failure=YES;reason=@"frame_shape_identity";break;}
            NSMutableData *payload=[NSMutableData dataWithLength:payloadLen];
            if(!exactRead(peer,payload.mutableBytes,payloadLen)){failure=YES;reason=@"short_payload";break;}
            if(crc32(0,payload.bytes,(uInt)payloadLen)!=crc){failure=YES;reason=@"crc32";break;}
            lastSeq=seq;
            [stateLock lock];int index=-1;
            for(int i=0;i<2;i++)if([slots[i][@"state"] isEqual:@"READY"]){terminal(slots[i],@"replaced");slots[i]=nil;}
            for(int i=0;i<2;i++)if(!slots[i]){index=i;break;}
            if(index<0){[stateLock unlock];failure=YES;reason=@"slot_exhausted";break;}
            slots[index]=[@{@"index":@(index),@"state":@"WRITING",@"header":h,@"payload":payload,@"received_ns":@(nowNS())} mutableCopy];
            // Mutex is publication barrier; ACK precedes making READY visible to UI.
            ack(@{@"ack_for":@"FRAME",@"stage":@"RECEIVED",@"sid":@1,@"gen":@(gen),@"seq":@(seq),@"slot":@(index),@"crc32":@(crc),@"host_ns":@(nowNS()),@"ready_depth":@1});
            slots[index][@"state"]=@"READY";[stateLock unlock];
        } else if([type isEqual:@"ARM"]) {
            BOOL closeEvent=[h[@"close"] boolValue];uint64_t armed=nowNS();
            dispatch_after(dispatch_time(DISPATCH_TIME_NOW,250*NSEC_PER_MSEC),dispatch_get_global_queue(QOS_CLASS_USER_INITIATED,0),^{
                NSEvent *event=[NSEvent otherEventWithType:NSEventTypeApplicationDefined location:NSZeroPoint modifierFlags:0 timestamp:0 windowNumber:window.windowNumber context:nil subtype:closeEvent?2:1 data1:0 data2:0];[NSApp postEvent:event atStart:NO];
            });
            ack(@{@"ack_for":@"ARM",@"stage":@"ARMED",@"host_ns":@(armed),@"due_ns":@(armed+250000000),@"close":@(closeEvent)});
        } else if([type isEqual:@"CLOSE"]) {
            dispatch_sync(dispatch_get_main_queue(),^{consume();});
            ack(@{@"ack_for":@"CLOSE",@"stage":@"CLOSED"});reason=@"close";break;
        } else {failure=YES;reason=@"message_type";break;}
    }}
    if(failure)ack(@{@"type":@"ERROR",@"reason":reason});
    dispatch_async(dispatch_get_main_queue(),^{
        [stateLock lock];for(int i=0;i<2;i++)if(slots[i]){terminal(slots[i],@"invalidated");slots[i]=nil;}[stateLock unlock];
        stopHost(reason);
    });
    }
}
int main(int argc,const char **argv) {@autoreleasepool {
    if(argc!=3){fprintf(stderr,"usage: presenter SOCKET DISPLAY_HZ\n");return 2;}
    signal(SIGPIPE,SIG_IGN);stateLock=[NSLock new];sendLock=[NSLock new];
    [LabApp sharedApplication];[NSApp setActivationPolicy:NSApplicationActivationPolicyAccessory];[NSApp finishLaunching];
    if(!NSScreen.mainScreen){fprintf(stderr,"no screen\n");return 3;}
    window=[[NSWindow alloc] initWithContentRect:NSMakeRect(180,180,64,64) styleMask:NSWindowStyleMaskTitled|NSWindowStyleMaskClosable backing:NSBackingStoreBuffered defer:NO];
    Delegate *delegate=[Delegate new];window.delegate=delegate;window.releasedWhenClosed=NO;window.title=@"P1 A-copy CPU transport (host only)";window.colorSpace=NSColorSpace.sRGBColorSpace;
    view=[[NSImageView alloc] initWithFrame:NSMakeRect(0,0,64,64)];view.imageScaling=NSImageScaleNone;view.imageAlignment=NSImageAlignTopLeft;view.wantsLayer=YES;view.layer.minificationFilter=kCAFilterNearest;view.layer.magnificationFilter=kCAFilterNearest;window.contentView=view;[window makeKeyAndOrderFront:nil];
    listener=socket(AF_UNIX,SOCK_STREAM,0);struct sockaddr_un addr={0};addr.sun_family=AF_UNIX;
    if(strlen(argv[1])>=sizeof(addr.sun_path)){fprintf(stderr,"socket path too long\n");return 4;}strcpy(addr.sun_path,argv[1]);
    if(bind(listener,(struct sockaddr*)&addr,sizeof(addr))||listen(listener,1)){perror("listen");return 5;}
    double hz=atof(argv[2]);if(hz<1||hz>1000)return 6;
    NSTimer *timer=[NSTimer scheduledTimerWithTimeInterval:1.0/hz repeats:YES block:^(NSTimer *t){consume();}];
    logJSON(@{@"event":@"ready",@"pid":@(getpid()),@"host_ns":@(nowNS()),@"scale":@(NSScreen.mainScreen.backingScaleFactor),@"display_hz":@(hz)});
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED,0),^{reader();});
    [NSApp run];[timer invalidate];[window orderOut:nil];if(peer>=0)close(peer);close(listener);
    // Socket pathname lives in the unique run directory; retain as evidence, never unlink external paths.
    logJSON(@{@"event":@"exit",@"host_ns":@(nowNS())});return 0;
}}

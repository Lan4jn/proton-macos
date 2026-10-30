from pathlib import Path
import shutil
LAB=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent
s=(LAB/'sources/vk-throughput-probe/vk_throughput_x64.c').read_text()
s=s.replace('static unsigned bench_width=','struct PixelPacket {uint64_t ready,seq,phase,width,height,pitch,payload_bytes;unsigned char pixels[1920*1080*4];};\nvolatile struct PixelPacket inproc_packet;\nstatic unsigned bench_width=')
s=s.replace('unsigned char *pixels=0;bench_check(pvkMapMemory', 'unsigned char *pixels=0;bench_check(pvkMapMemory')
s=s.replace('          pvkUnmapMemory(device,stagingBufferMemory);', '''          pvkUnmapMemory(device,stagingBufferMemory);
          if(g==1){
            for(unsigned q=0;q<FB_SIZE;q++)inproc_packet.pixels[q]=bench_snapshot[q];
            inproc_packet.width=FB_WIDTH;inproc_packet.height=FB_HEIGHT;inproc_packet.pitch=FB_WIDTH*4;inproc_packet.payload_bytes=FB_SIZE;inproc_packet.phase=1;inproc_packet.seq++;inproc_packet.ready=0x504958454c;
            /* Ordinary stdout write reaches the existing syscall safe point; no new hypercall. */
            inproc_packet.pixels[0]=(unsigned char)inproc_packet.seq; /* explicit CPU identity watermark */
            print_str("INPROC_FRAME_COMMIT seq=");bench_num(inproc_packet.seq);print_str("\\n");
          }''')
s=s.replace('    /* Step 11: Cleanup */', '    inproc_packet.phase=4;print_str("INPROC_FRAME_END\\n");\n    /* Step 11: Cleanup */')
s=s.replace('WIN_X64_THROUGHPUT_OK','WIN_ARM64_INPROC_FRAME_OK')
(OUT/'frame_probe_arm64.c').write_text(s)
(OUT/'kernel32.def').write_text((LAB/'sources/vk-throughput-probe/kernel32.def').read_text())
shutil.copy2(LAB/'sources/vk-throughput-probe/shaders/shaders_spv.h',OUT/'shaders_spv.h')

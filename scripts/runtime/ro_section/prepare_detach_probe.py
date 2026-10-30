#!/usr/bin/env python3
"""Boundary-only transition test; not production view bookkeeping."""
from pathlib import Path
import difflib
LAB=Path(__file__).resolve().parents[3]
OUT=LAB/'sources/wine-ro-section-adapt'
old=(OUT/'approved_candidate.c').read_text()
transition='''
static int change_shared_readonly_protection(void *base, size_t size, int fd,
                                           off_t offset, BYTE vprot, int *shared)
{
    if (*shared && (vprot & VPROT_WRITECOPY) && !(vprot & VPROT_WRITE))
    {
        /* Rebind read-only first; only the requested mprotect can grant write. */
        if (mmap(base, size, PROT_READ, MAP_FIXED | MAP_PRIVATE, fd, offset) == MAP_FAILED)
            return -1;
        *shared = 0;
    }
    return mprotect(base, size, get_unix_prot(vprot));
}
'''
write_test='''
 struct file_view write_upgrade=reserve(p);
 REQUIRE(map_file_into_view(&write_upgrade,fd,0,p,0,VPROT_COMMITTED|VPROT_READ,0)==0);
 REQUIRE(mprotect(write_upgrade.base,p,get_unix_prot(VPROT_COMMITTED|VPROT_READ))==0);
 int shared_write=1;
 REQUIRE(change_shared_readonly_protection(write_upgrade.base,p,fd,0,
          VPROT_COMMITTED|VPROT_READ|VPROT_WRITE,&shared_write)==0);
 ((volatile unsigned char*)write_upgrade.base)[0]=0x43;
 result("READONLY_TO_WRITE_STILL_SHARED",shared_write && disk(fd)==0x43 && ((volatile unsigned char*)rw.base)[0]==0x43);
 REQUIRE(pwrite(fd,&update,1,0)==1);
 munmap(write_upgrade.base,p);
'''
# Add WRITE regression to both RED and GREEN, without changing historical evidence.
red=old.replace('int main(void){',transition.replace('if (*shared && (vprot & VPROT_WRITECOPY) && !(vprot & VPROT_WRITE))','if (0)')+'\nint main(void){',1)
red=red.replace(' // NtProtect ->',write_test+'\n // NtProtect ->',1)
old_final=' REQUIRE(mprotect(ro.base,p,prot)==0);'
new_final=' int shared_ro=1;\n REQUIRE(change_shared_readonly_protection(ro.base,p,fd,0,VPROT_COMMITTED|VPROT_READ|VPROT_WRITECOPY,&shared_ro)==0);'
assert red.count(old_final)==1
red=red.replace(old_final,new_final)
green=red.replace('if (0)','if (*shared && (vprot & VPROT_WRITECOPY) && !(vprot & VPROT_WRITE))',1)
red=red.replace('MODE "approved_candidate"','MODE "detach_red"')
green=green.replace('MODE "approved_candidate"','MODE "detach_green"')
(OUT/'detach_red.c').write_text(red)
(OUT/'detach_green.c').write_text(green)
(LAB/'logs/ro-section/detach-boundary.patch').write_text(''.join(difflib.unified_diff(red.splitlines(True),green.splitlines(True),fromfile='detach_red.c',tofile='detach_green.c')))
print('Prepared RED and GREEN boundary variants, original exit42 evidence preserved')

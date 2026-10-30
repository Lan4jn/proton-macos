#!/usr/bin/env python3
from pathlib import Path
import difflib
LAB=Path(__file__).resolve().parents[3]
P=LAB/'sources/wine-ro-section-adapt/wine/dlls/ntdll/unix/virtual.c'
s=P.read_text()
assert 'struct ro_file_range' not in s
block=r'''
/* virtual_mutex protects this address-based list, including view splits. */
struct ro_file_range
{
    struct ro_file_range *next;
    char *base;
    size_t size;
    off_t offset;
    int fd;
    BYTE pages[1]; /* 0 shared, 1 detached, 2 unmapped */
};
static struct ro_file_range *ro_file_ranges;
static size_t ro_tracked_ranges, ro_detached_via_fd, ro_detached_via_copy, ro_detach_failed;

static void ro_range_log( const char *event, const void *base, size_t size, off_t offset, int fd )
{
    fprintf( stderr, "RO_SECTION event=%s pid=%u base=%p size=%#lx offset=%#llx fd=%d "
             "tracked_ranges=%lu detached_via_fd=%lu detached_via_copy=%lu detach_failed=%lu\n",
             event, (unsigned int)getpid(), base, (unsigned long)size, (unsigned long long)offset, fd,
             (unsigned long)ro_tracked_ranges, (unsigned long)ro_detached_via_fd,
             (unsigned long)ro_detached_via_copy, (unsigned long)ro_detach_failed );
}

static void ro_forget_range( const void *base, size_t size )
{
    struct ro_file_range **link = &ro_file_ranges, *range;
    char *first = ROUND_ADDR( base, host_page_mask );
    char *end = first + ROUND_SIZE( base, size, host_page_mask );
    size_t i, count;

    while ((range = *link))
    {
        count = range->size / host_page_size;
        for (i = 0; i < count; i++)
            if (range->base + i * host_page_size >= first && range->base + i * host_page_size < end)
                range->pages[i] = 2;
        for (i = 0; i < count && range->pages[i] == 2; i++);
        if (i < count) { link = &range->next; continue; }
        *link = range->next;
        if (range->fd >= 0) close( range->fd );
        ro_tracked_ranges--;
        ro_range_log( "release", range->base, range->size, range->offset, range->fd );
        free( range );
    }
}

static struct ro_file_range *ro_prepare_range( char *base, size_t size, int fd, off_t offset )
{
    struct ro_file_range *range = calloc( 1, sizeof(*range) + size / host_page_size );
    if (!range) return NULL;
    range->base = base;
    range->size = size;
    range->offset = offset;
    range->fd = dup( fd );
    if (range->fd >= 0 && fcntl( range->fd, F_SETFD, FD_CLOEXEC ) == -1)
    {
        close( range->fd );
        range->fd = -1;
    }
    if (range->fd < 0) ro_range_log( "dup_failed_copy_on_upgrade", base, size, offset, -1 );
    return range;
}

static NTSTATUS ro_detach_writecopy( void *base, size_t size, BYTE vprot )
{
    struct ro_file_range *range;
    char *first = ROUND_ADDR( base, host_page_mask );
    char *end = first + ROUND_SIZE( base, size, host_page_mask );
    char *addr;
    size_t i, count;
    int old_prot;
    void *snapshot;
    off_t offset;

    if (!(vprot & VPROT_WRITECOPY) || (vprot & VPROT_WRITE)) return STATUS_SUCCESS;
    for (range = ro_file_ranges; range; range = range->next)
    {
        count = range->size / host_page_size;
        for (i = 0; i < count; i++)
        {
            addr = range->base + i * host_page_size;
            if (range->pages[i] || addr < first || addr >= end) continue;
            offset = range->offset + i * host_page_size;
            if (range->fd >= 0)
            {
                if (mmap( addr, host_page_size, PROT_READ, MAP_FIXED | MAP_PRIVATE,
                          range->fd, offset ) == MAP_FAILED) goto failed;
                ro_detached_via_fd++;
            }
            else
            {
                ro_range_log( "no_fd_copy_begin", addr, host_page_size, offset, -1 );
                if (!(snapshot = malloc( host_page_size ))) goto failed;
                old_prot = get_unix_prot( get_page_vprot( addr ));
                if (mprotect( addr, host_page_size, PROT_READ )) { free( snapshot ); goto failed; }
                memcpy( snapshot, addr, host_page_size );
                if (mprotect( addr, host_page_size, old_prot )) { free( snapshot ); goto failed; }
                if (mmap( addr, host_page_size, PROT_READ | PROT_WRITE,
                          MAP_FIXED | MAP_PRIVATE | MAP_ANON, -1, 0 ) == MAP_FAILED)
                { free( snapshot ); goto failed; }
                memcpy( addr, snapshot, host_page_size );
                free( snapshot );
                /* Internal snapshot writes are over before requested permissions are applied. */
                if (mprotect( addr, host_page_size, PROT_READ ))
                {
                    mprotect( addr, host_page_size, PROT_NONE );
                    range->pages[i] = 1;
                    goto failed;
                }
                ro_detached_via_copy++;
            }
            range->pages[i] = 1;
            ro_range_log( range->fd >= 0 ? "detach_fd" : "detach_copy", addr,
                          host_page_size, offset, range->fd );
        }
    }
    return STATUS_SUCCESS;
failed:
    ro_detach_failed++;
    ro_range_log( "detach_failed", addr, host_page_size, offset, range->fd );
    return STATUS_NO_MEMORY;
}
'''
# Same TU, no test hooks or unit-only policy branches.
anchor='\n\n/***********************************************************************\n *           dump_view'
assert s.count(anchor)==1
s=s.replace(anchor,'\n'+block+anchor,1)
s=s.replace('''    if (!set_vprot( view, base, size, vprot | VPROT_COMMITTED )) return STATUS_ACCESS_DENIED;''','''    if ((status = ro_detach_writecopy( base, size, vprot ))) return status;
    if (!set_vprot( view, base, size, vprot | VPROT_COMMITTED )) return STATUS_ACCESS_DENIED;''',1)
s=s.replace('''    if (!(size = unmap_area_above_user_limit( start, size ))) return;''','''    ro_forget_range( start, size );
    if (!(size = unmap_area_above_user_limit( start, size ))) return;''',1)
s=s.replace('''    view->protect = VPROT_PLACEHOLDER | VPROT_FREE_PLACEHOLDER;
    set_page_vprot''','''    ro_forget_range( view->base, view->size );
    view->protect = VPROT_PLACEHOLDER | VPROT_FREE_PLACEHOLDER;
    set_page_vprot''',1)
s=s.replace('''    unsigned int flags = MAP_FIXED;

    assert( start < view->size );''','''    unsigned int flags = MAP_FIXED;
    struct ro_file_range *ro_range = NULL;
    struct stat observed;

    assert( start < view->size );''',1)
old='''        if (mmap( host_addr, host_size, prot, flags, fd, offset ) != MAP_FAILED)
            return STATUS_SUCCESS;

        switch (errno)'''
new='''        if (!(vprot & (VPROT_WRITE | VPROT_WRITECOPY)))
        {
            if (!(ro_range = ro_prepare_range( host_addr, host_size, fd, offset )))
                return STATUS_NO_MEMORY;
        }
        if (mmap( host_addr, host_size, prot, flags, fd, offset ) != MAP_FAILED)
        {
            ro_forget_range( host_addr, host_size );
            if (ro_range)
            {
                ro_range->next = ro_file_ranges;
                ro_file_ranges = ro_range;
                ro_tracked_ranges++;
                ro_range_log( "mmap_success", host_addr, host_size, offset, ro_range->fd );
                if (!fstat( fd, &observed ))
                    fprintf( stderr, "RO_SECTION origin=map_file_into_view size=%#lx offset=%#llx "
                             "unlinked=%d prot=%x vprot=%x caller=%p\\n", (unsigned long)host_size,
                             (unsigned long long)offset, !observed.st_nlink, prot, vprot,
                             __builtin_return_address(0) );
            }
            return STATUS_SUCCESS;
        }
        if (ro_range)
        {
            int saved_errno = errno;
            if (ro_range->fd >= 0) close( ro_range->fd );
            free( ro_range );
            errno = saved_errno;
        }

        switch (errno)'''
assert s.count(old)==1;s=s.replace(old,new,1)
s=s.replace('''    mprotect( map_addr, map_size, PROT_READ | PROT_WRITE );
    pread( fd, map_addr, size, offset );''','''    if (!(vprot & (VPROT_WRITE | VPROT_WRITECOPY)))
        ro_range_log( "pread_fallback", map_addr, map_size, offset, fd );
    ro_forget_range( map_addr, map_size );
    mprotect( map_addr, map_size, PROT_READ | PROT_WRITE );
    pread( fd, map_addr, size, offset );''',1)
P.write_text(s)
base=LAB/'sources/wine-pin-adea/pristine/wine-adea6cbac9d00bb22910145354d00c463fcf3afc/dlls/ntdll/unix/virtual.c'
(LAB/'logs/ro-section/production.patch').write_text(''.join(difflib.unified_diff(base.read_text().splitlines(True),s.splitlines(True),fromfile='a/dlls/ntdll/unix/virtual.c',tofile='b/dlls/ntdll/unix/virtual.c')))
print('Applied same-source production tracking and conditional detach only to virtual.c')

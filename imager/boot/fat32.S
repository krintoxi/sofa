/*
 * Sofa Box Imager's FAT32 boot sector for the Windows sticks. Ours: it doesn't read the file system at all. The Imager
 * lays BOOTMGR (Windows' BIOS boot manager) out in one unbroken run of clusters and writes where it starts and how
 * many sectors it takes into this sector (at 0x1F6 and 0x1FA), so the code only has to read that run.
 *
 * The MBR loads it at 0000:7C00 with the drive in DL. It reads BOOTMGR by LBA (INT 13h, AH=42h, 32 KB at a time) to
 * 2000:0000 and jumps there with DL the drive and this sector, with its BPB, still at 0000:7C00: what Windows' own
 * boot sector hands BOOTMGR (BOOTMGR reads the BPB to find its partition).
 *
 * Bytes 3 to 0x59 are the BPB, filled in by the Imager (FAT32Stick); they're zero here.
 *
 * Build (Xcode's own clang; BootCode.swift holds the bytes, and a test checks they're these):
 *   xcrun clang -c -target i386-unknown-none-elf fat32.S -o fat32.o
 */
        .code16
        .text
        .globl  _start
_start:
        jmp     boot
        nop
        .fill   0x5a - 3, 1, 0
boot:
        cli
        xorw    %ax, %ax
        movw    %ax, %ss
        movw    $0x7c00, %sp
        movw    %ax, %ds
        movw    %ax, %es
        sti
        cld
        ljmp    $0, $(0x7c00 + here - _start)
here:
        movb    %dl, (0x7c00 + 0x40)            /* BS_DrvNum */
        movb    $0x41, %ah                      /* are the LBA calls there? */
        movw    $0x55aa, %bx
        int     $0x13
        jc      no_lba
        cmpw    $0xaa55, %bx
        jne     no_lba
        movl    (0x7c00 + 0x1c), %eax           /* BPB_HiddSec: where the partition starts */
        addl    (0x7c00 + 0x1f6), %eax          /* plus where BOOTMGR starts in it */
        movl    %eax, (0x7c00 + dap_lba - _start)
        movw    (0x7c00 + 0x1fa), %cx           /* its length in sectors */
        jcxz    no_loader
        movw    $0x2000, %bx                    /* segment it goes to */
next:
        movw    %cx, %ax
        cmpw    $64, %ax
        jbe     1f
        movw    $64, %ax
1:
        movw    %ax, (0x7c00 + dap_count - _start)
        movw    %bx, (0x7c00 + dap_segment - _start)
        pushw   %ax
        pushw   %bx
        pushw   %cx
        movw    $(0x7c00 + dap - _start), %si
        movb    $0x42, %ah
        movb    (0x7c00 + 0x40), %dl
        int     $0x13
        popw    %cx
        popw    %bx
        popw    %ax
        jc      read_error
        subw    %ax, %cx
        movzwl  %ax, %edx
        addl    %edx, (0x7c00 + dap_lba - _start)
        shlw    $5, %ax                         /* sectors of 512 bytes, in 16-byte paragraphs */
        addw    %ax, %bx
        testw   %cx, %cx
        jnz     next
        movb    (0x7c00 + 0x40), %dl
        ljmp    $0x2000, $0
no_lba:
        movw    $(0x7c00 + msg_lba - _start), %si
        jmp     fail
no_loader:
        movw    $(0x7c00 + msg_loader - _start), %si
        jmp     fail
read_error:
        movw    $(0x7c00 + msg_read - _start), %si
fail:
        lodsb
        testb   %al, %al
        jz      halt
        movb    $0x0e, %ah
        movw    $7, %bx
        int     $0x10
        jmp     fail
halt:
        hlt
        jmp     halt

dap:    .byte   16, 0
dap_count:
        .word   0
        .word   0                               /* offset 0 */
dap_segment:
        .word   0
dap_lba:
        .long   0, 0
msg_lba:
        .asciz  "No LBA disk calls"
msg_loader:
        .asciz  "No BOOTMGR"
msg_read:
        .asciz  "Disk read error"

        .org    0x1f6
loader_sector:                                  /* filled in by the Imager */
        .long   0
loader_count:
        .word   0
        .word   0
        .word   0xaa55

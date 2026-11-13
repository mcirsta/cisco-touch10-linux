/* SPDX-License-Identifier: GPL-2.0-only */
/* Replay captured controller data and malformed inputs under ASan/UBSan. */
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef uint8_t u8;
typedef uint16_t u16;
#include "cyttsp4_protocol.h"

static void load(const char *path, void *data, size_t size)
{
    FILE *f=fopen(path,"rb");
    assert(f);
    assert(fread(data,1,size,f)==size);
    fclose(f);
}

int main(int argc, char **argv)
{
    u8 sysinfo[256], original[256], data[256]={0};
    struct cy4_layout layout, changed;
    struct cy4_contact contacts[CY4_MAX_CONTACTS];
    assert(argc==3);
    load(argv[1],sysinfo,sizeof(sysinfo));
    assert(cy4_parse_sysinfo(sysinfo,sizeof(sysinfo),&layout)==0);
    assert(layout.max_x==1280 && layout.max_y==800 && layout.max_contacts==10);
    assert(layout.record_size==7 && layout.frame_size==82);
    FILE *frames=fopen(argv[2],"rb");
    assert(frames);
    unsigned samples=0, active=0, releases=0, two=0;
    while (fread(data,1,64,frames)==64) {
        int count=cy4_parse_report(&layout,data,64,contacts);
        assert(count>=0);
        samples++;
        if (count) active++;
        else releases++;
        if ((data[11]&31)==2) two++;
        if (samples==2) {
            assert(count==1 && contacts[0].x==602 && contacts[0].y==403);
            assert(contacts[0].id==1 && contacts[0].pressure==14);
        }
        if (samples==12)
            assert(count==1 && contacts[0].id==2 && contacts[0].x==808 && contacts[0].y==548);
    }
    fclose(frames);
    assert(samples>=10 && active && releases && two);
    /* Ten contacts require bytes beyond the old bridge's 64-byte read. */
    memset(data,0,sizeof(data));
    data[9]=72;
    data[11]=10;
    for (unsigned i=0;i<10;i++) {
        u8 *record=data+12+7*i;
        record[1]=100+i;
        record[3]=200;
        record[4]=20;
        record[5]=0x20+i;
        record[6]=3;
    }
    assert(cy4_parse_report(&layout,data,82,contacts)==10);
    assert(contacts[9].x==109 && contacts[9].id==9);
    for (size_t size=0;size<82;size++)
        assert(cy4_parse_report(&layout,data,size,contacts)<0);
    memcpy(original,data,sizeof(data));
    data[11]=31;
    assert(cy4_parse_report(&layout,data,sizeof(data),contacts)<0);
    memcpy(data,original,sizeof(data));
    data[12+7+5]=data[12+5];
    assert(cy4_parse_report(&layout,data,sizeof(data),contacts)<0);
    memcpy(data,original,sizeof(data));
    data[12]=5; /* X > 1279. */
    assert(cy4_parse_report(&layout,data,sizeof(data),contacts)<0);
    memcpy(data,original,sizeof(data));
    for (unsigned i=0;i<10;i++) data[12+7*i+5]|=0x60;
    assert(cy4_parse_report(&layout,data,sizeof(data),contacts)==0);
    memcpy(data,original,sizeof(data));
    data[11]|=0x20; /* Palm. */
    assert(cy4_parse_report(&layout,data,sizeof(data),contacts)==0);
    /* Exhaust all single-byte corruptions of the real descriptor and frame. */
    for (unsigned byte=0;byte<256;byte++) {
        u8 saved=sysinfo[byte];
        for (unsigned value=0;value<256;value++) {
            sysinfo[byte]=value;
            int ret=cy4_parse_sysinfo(sysinfo,sizeof(sysinfo),&changed);
            if (!ret) cy4_parse_report(&changed,original,sizeof(original),contacts);
            memcpy(data,original,sizeof(data));
            data[byte]=value;
            cy4_parse_report(&layout,data,sizeof(data),contacts);
        }
        sysinfo[byte]=saved;
    }
    for (size_t size=0;size<256;size++)
        cy4_parse_sysinfo(sysinfo,size,&changed);
    printf("PASS captured_frames=%u active=%u releases=%u mixed_release_down=%u; ten contacts, truncation, IDs, release, palm and 131072 byte mutations\n",
           samples,active,releases,two);
    return 0;
}

/* Test double for FERSlib. No network or USB access.
 * Define FERSLIB_HEADER_CHECK to compile against an installed vendor header.
 */
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#ifdef FERSLIB_HEADER_CHECK
#include "FERSlib.h"
#else
typedef struct {
    uint32_t pid;
    uint16_t FERSCode;
    uint8_t PCBrevision;
    char ModelCode[16];
    char ModelName[16];
    uint8_t FormFactor;
    uint16_t NumCh;
    uint32_t FPGA_FWrev;
    uint32_t uC_FWrev;
} FERS_BoardInfo_t;
#endif

static int opened, closes, writes, fail, model = 5202, enabled;
static uint32_t register_value;
static float temperature = 24.5f, bias = 55.0f, current_limit = 1.0f;
static char error_text[1024];

/* Controls used by tests, never by production code. */
void stub_fail(int code) { fail = code; }
void stub_model(int code) { model = code; }
void stub_temperature(float value) { temperature = value; }
int stub_opened(void) { return opened; }
int stub_closes(void) { return closes; }
int stub_writes(void) { return writes; }

static int status(void) {
    int result = fail;
    fail = 0;
    if (result) strcpy(error_text, "simulated communication failure");
    return result;
}

char *FERS_GetLibReleaseNum(void) { return "2.2.2"; }
int FERS_GetLastError(char description[1024]) {
    strcpy(description, error_text);
    error_text[0] = '\0';
    return 0;
}
int FERS_OpenDevice(const char *path, int *handle) {
    int result = status();
    if (result) return result;
    if (strcmp(path, "eth:192.0.2.1") && strcmp(path, "usb:12345")) return -5;
    opened++;
    *handle = 0; /* Zero is a valid FERSlib handle. */
    return 0;
}
int FERS_CloseDevice(int handle) {
    int result = status();
    if (result) return result;
    if (handle != 0 || !opened) return -6;
    opened--;
    closes++;
    return 0;
}
int FERS_GetBoardInfo(int handle, FERS_BoardInfo_t *info) {
    int result = status();
    if (result) return result;
    if (handle != 0 || !opened) return -6;
    memset(info, 0, sizeof(*info));
    info->pid = 12345;
    info->FERSCode = model;
    info->PCBrevision = 3;
    strcpy(info->ModelCode, "WA5202XAAAAA");
    strcpy(info->ModelName, "A5202");
    info->NumCh = 64;
    info->FPGA_FWrev = 0xFEDCBA98;
    info->uC_FWrev = 0x87654321;
    return 0;
}
int FERS_ReadRegister(int handle, uint32_t address, uint32_t *value) {
    int result = status();
    if (result) return result;
    if (handle != 0 || address != 0xFFFFFFFF) return -14;
    *value = register_value;
    return 0;
}
int FERS_WriteRegister(int handle, uint32_t address, uint32_t value) {
    int result = status();
    if (result) return result;
    if (handle != 0 || address != 0xFFFFFFFF) return -14;
    register_value = value;
    writes++;
    return 0;
}

#define FLOAT_READER(name, expression) \
    int name(int handle, float *value) { \
        int result = status(); \
        if (result) return result; \
        if (handle != 0) return -6; \
        *value = (expression); \
        return 0; \
    }
FLOAT_READER(FERS_Get_Board_Temp, temperature)
FLOAT_READER(FERS_Get_FPGA_Temp, 42.25f)
FLOAT_READER(FERS_HV_Get_IntTemp, 30.0f)
FLOAT_READER(FERS_HV_Get_DetectorTemp, 21.75f)
FLOAT_READER(FERS_HV_Get_Vbias, bias)
FLOAT_READER(FERS_HV_Get_Vmon, bias - 0.1f)
FLOAT_READER(FERS_HV_Get_Imax, current_limit)
FLOAT_READER(FERS_HV_Get_Imon, 0.1234f)

int FERS_HV_Get_Status(int handle, int *on, int *ramp, int *ovc, int *ovv) {
    int result = status();
    if (result) return result;
    if (handle != 0) return -6;
    *on = enabled; *ramp = 1; *ovc = 0; *ovv = 1;
    return 0;
}
int FERS_HV_Set_OnOff(int handle, int on) {
    int result = status();
    if (result) return result;
    if (handle != 0) return -6;
    enabled = on;
    writes++;
    return 0;
}
int FERS_HV_Set_Vbias(int handle, float value) {
    int result = status();
    if (result) return result;
    if (handle != 0) return -6;
    bias = value;
    writes++;
    return 0;
}
int FERS_HV_Set_Imax(int handle, float value) {
    int result = status();
    if (result) return result;
    if (handle != 0) return -6;
    current_limit = value;
    writes++;
    return 0;
}

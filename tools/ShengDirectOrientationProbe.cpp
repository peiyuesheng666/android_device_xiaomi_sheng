// SPDX-License-Identifier: Apache-2.0
#include <android/hardware_buffer.h>
#include <android/sensor.h>
#include <unistd.h>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <map>
#include <array>

int main() {
    constexpr size_t bytes = 104 * 256;
    ASensorManager* manager = ASensorManager_getInstanceForPackage("org.lineageos.sheng.displaydefaults");
    if (!manager) return 1;
    AHardwareBuffer_Desc description{};
    description.width = bytes;
    description.height = description.layers = 1;
    description.format = AHARDWAREBUFFER_FORMAT_BLOB;
    description.usage = AHARDWAREBUFFER_USAGE_SENSOR_DIRECT_DATA | AHARDWAREBUFFER_USAGE_CPU_READ_OFTEN;
    AHardwareBuffer* buffer = nullptr;
    int status = AHardwareBuffer_allocate(&description, &buffer);
    printf("HARDWARE_BUFFER allocation=%d\n", status);
    if (status != 0) return 2;
    int channel = ASensorManager_createHardwareBufferDirectChannel(manager, buffer, bytes);
    printf("DIRECT_CHANNEL id=%d\n", channel);
    if (channel <= 0) { AHardwareBuffer_release(buffer); return 3; }
    for (int type : {ASENSOR_TYPE_ACCELEROMETER, ASENSOR_TYPE_GYROSCOPE, ASENSOR_TYPE_MAGNETIC_FIELD}) {
        const ASensor* sensor = ASensorManager_getDefaultSensor(manager, type);
        if (sensor) {
            printf("DIRECT_REGISTER type=%d token=%d\n", type,
                ASensorManager_configureDirectReport(manager, sensor, channel, ASENSOR_DIRECT_RATE_NORMAL));
        }
    }
    fflush(stdout);
    usleep(6000000);
    ASensorManager_configureDirectReport(manager, nullptr, channel, ASENSOR_DIRECT_RATE_STOP);
    void* address = nullptr;
    status = AHardwareBuffer_lock(buffer, AHARDWAREBUFFER_USAGE_CPU_READ_OFTEN, -1, nullptr, &address);
    printf("HARDWARE_BUFFER lock=%d\n", status);
    std::map<int, std::array<double, 4>> sums;
    if (status == 0) {
        auto* data = static_cast<const uint8_t*>(address);
        for (size_t offset = 0; offset < bytes; offset += 104) {
            int size, type;
            uint32_t sequence;
            float xyz[3];
            memcpy(&size, data + offset, 4);
            memcpy(&type, data + offset + 8, 4);
            memcpy(&sequence, data + offset + 12, 4);
            memcpy(xyz, data + offset + 24, 12);
            if (size != 104 || sequence == 0) continue;
            auto& sum = sums[type];
            for (int axis = 0; axis < 3; axis++) sum[axis] += xyz[axis];
            sum[3]++;
        }
        AHardwareBuffer_unlock(buffer, nullptr);
    }
    for (const auto& [type, sum] : sums) {
        printf("DIRECT_AVERAGE type=%d count=%.0f xyz=[%.8f,%.8f,%.8f]\n",
               type, sum[3], sum[0]/sum[3], sum[1]/sum[3], sum[2]/sum[3]);
    }
    ASensorManager_destroyDirectChannel(manager, channel);
    AHardwareBuffer_release(buffer);
    return sums.empty() ? 4 : 0;
}

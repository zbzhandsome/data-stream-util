#ifndef ENC_H
#define ENC_H

#include <cstdint>
#include <string>

static inline std::string d(const uint8_t* p, size_t n) {
    std::string s(n, '\0');
    for (size_t i = 0; i < n; i++) s[i] = static_cast<char>(p[i] ^ 0x55);
    return s;
}

#endif

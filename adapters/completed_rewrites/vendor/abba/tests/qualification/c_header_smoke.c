#include "abba_c.h"

#include <stddef.h>

int main(void) {
  const double values[2] = {0.0, 1.0};
  const abba_config_v1 config = abba_config_default_v1();
  size_t required = 0;
  const abba_status_v1 status = abba_encode_v1(
      values, 2, &config, NULL, 0, &required, NULL);
  return status == ABBA_STATUS_BUFFER_TOO_SMALL_V1 && required > 0 ? 0 : 1;
}

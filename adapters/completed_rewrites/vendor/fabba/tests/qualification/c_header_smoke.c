#include "fabba_c.h"

#include <stddef.h>

int main(void) {
  const double values[2] = {0.0, 1.0};
  const fabba_config_v1 config = fabba_config_default_v1();
  size_t required = 0;
  const fabba_status_v1 status = fabba_encode_v1(
      values, 2, &config, NULL, 0, &required, NULL);
  return status == FABBA_STATUS_BUFFER_TOO_SMALL_V1 && required > 0 ? 0 : 1;
}

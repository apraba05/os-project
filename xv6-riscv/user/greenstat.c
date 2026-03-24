#include "kernel/types.h"
#include "kernel/stat.h"
#include "user/user.h"

#define NPROC 64

int
main(void)
{
  int pid;
  int count = 0;
  uint64 total = 0;

  printf("GreenX Energy Report\n");
  printf("--------------------\n");
  printf("PID\tTICKS\n");

  for(pid = 1; pid <= NPROC; pid++) {
    int ticks = getpenergy(pid);
    if(ticks == -1)
      continue;
    printf("%d\t%d\n", pid, ticks);
    total += ticks;
    count++;
  }

  printf("--------------------\n");
  printf("Processes: %d  |  Total ticks: %d\n", count, (int)total);

  exit(0);
}

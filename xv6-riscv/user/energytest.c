#include "kernel/types.h"
#include "kernel/stat.h"
#include "user/user.h"

static int passed = 0;

static void
report(int test, int ok)
{
  if(ok) {
    printf("Test %d: PASS\n", test);
    passed++;
  } else {
    printf("Test %d: FAIL\n", test);
  }
}

int
main(void)
{
  printf("=== GreenX energytest ===\n");

  // Test 1: seturgency valid and invalid values
  {
    int ok = 1;
    if(seturgency(0) != 0) ok = 0;
    if(seturgency(1) != 0) ok = 0;
    if(seturgency(2) != 0) ok = 0;
    if(seturgency(99) != -1) ok = 0;
    report(1, ok);
    seturgency(1); // restore to NORMAL
  }

  // Test 2: getpenergy increases after a busy loop; invalid pid returns -1
  {
    int mypid = getpid();
    int before = getpenergy(mypid);
    // busy loop to consume some ticks
    volatile long i;
    for(i = 0; i < 100000000L; i++)
      ;
    int after = getpenergy(mypid);
    int invalid = getpenergy(9999);
    int ok = (before >= 0) && (after > before) && (invalid == -1);
    report(2, ok);
  }

  // Test 3: fork a child that sleeps, verify exit status 0
  {
    int pid = fork();
    if(pid == 0) {
      pause(5);
      exit(0);
    }
    int status;
    int ret = wait(&status);
    int ok = (ret == pid) && (status == 0);
    report(3, ok);
  }

  // Test 4: fork a child with a budget, verify it gets killed
  {
    int pid = fork();
    if(pid == 0) {
      setbudget(3);
      // spin forever — budget enforcement should kill us
      volatile long i;
      for(i = 0; ; i++)
        ;
      exit(0); // unreachable
    }
    // parent waits; child should be killed by GreenX
    printf("Test 4: (check console for budget-exceeded message)\n");
    int status;
    int ret = wait(&status);
    // ret should be the child's pid (killed processes still get waited on)
    int ok = (ret == pid);
    report(4, ok);
  }

  // Test 5: low-urgency child can still call getpenergy on itself
  {
    seturgency(0);
    int pid = fork();
    if(pid == 0) {
      int mypid = getpid();
      int e = getpenergy(mypid);
      if(e >= 0)
        exit(0);
      else
        exit(1);
    }
    seturgency(1); // parent back to normal
    int status;
    int ret = wait(&status);
    int ok = (ret == pid) && (status == 0);
    report(5, ok);
  }

  // Test 6: fork a child that exec's greenstat
  {
    int pid = fork();
    if(pid == 0) {
      char *args[] = { "greenstat", 0 };
      exec("greenstat", args);
      exit(1); // if exec fails
    }
    int status;
    int ret = wait(&status);
    int ok = (ret == pid) && (status == 0);
    report(6, ok);
  }

  printf("=== %d/6 tests passed ===\n", passed);
  exit(0);
}

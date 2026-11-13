// SPDX-License-Identifier: GPL-2.0-only
/* Deterministic two-core work with read-only INA/clock/temperature sampling. */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <glob.h>
#include <inttypes.h>
#include <pthread.h>
#include <sched.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#define WORDS 8192u
#define MAX_SAMPLES 1000u
#define SAMPLE_NS 200000000L

struct worker {
	pthread_t thread;
	pthread_barrier_t *barrier;
	atomic_int *done;
	atomic_int *abort;
	uint32_t iterations, seed, result;
	int cpu, affinity_error;
	long long elapsed_ns;
};

struct sensors {
	int freq, regulator, temperature, mpu_mv, mpu_ma, five_mv, five_ma;
};

static struct sensors sensors = { -1, -1, -1, -1, -1, -1, -1 };

static long long nanoseconds(const struct timespec *t)
{
	return (long long)t->tv_sec * 1000000000LL + t->tv_nsec;
}

static uint32_t do_work(uint32_t iterations, uint32_t seed,
			const atomic_int *abort)
{
	uint32_t data[WORDS], state = seed, sum = 2166136261u;
	uint32_t i;

	for (i = 0; i < WORDS; i++)
		data[i] = seed ^ (i * 2654435761u);
	for (i = 0; i < iterations; i++) {
		uint32_t index, value;
		if (abort && !(i & 8191u) &&
		    atomic_load_explicit(abort, memory_order_relaxed))
			return 0;

		state ^= state << 13;
		state ^= state >> 17;
		state ^= state << 5;
		index = (state + (i >> 3)) & (WORDS - 1u);
		value = data[index];
		value = (value << 7) | (value >> 25);
		value += state ^ i;
		data[index] = value;
		sum = (sum ^ value) * 16777619u;
	}
	for (i = 0; i < WORDS; i++)
		sum = (sum ^ data[i]) * 16777619u;
	return sum ^ state;
}

static void *worker_main(void *argument)
{
	struct worker *w = argument;
	struct timespec start, end;
	cpu_set_t cpus;

	CPU_ZERO(&cpus);
	CPU_SET(w->cpu, &cpus);
	w->affinity_error = pthread_setaffinity_np(pthread_self(), sizeof(cpus), &cpus);
	pthread_barrier_wait(w->barrier);
	clock_gettime(CLOCK_MONOTONIC_RAW, &start);
	if (!w->affinity_error)
		w->result = do_work(w->iterations, w->seed, w->abort);
	clock_gettime(CLOCK_MONOTONIC_RAW, &end);
	w->elapsed_ns = nanoseconds(&end) - nanoseconds(&start);
	atomic_fetch_add_explicit(w->done, 1, memory_order_release);
	return NULL;
}

static int number_fd(int fd, long *result)
{
	char text[40], *end;
	ssize_t count;
	long value;

	if (lseek(fd, 0, SEEK_SET) < 0)
		return -1;
	count = read(fd, text, sizeof(text) - 1);
	if (count <= 0)
		return -1;
	text[count] = '\0';
	errno = 0;
	value = strtol(text, &end, 10);
	if (errno || end == text || value < -100000 || value > 2000000)
		return -1;
	*result = value;
	return 0;
}

static int open_one(const char *pattern)
{
	glob_t paths = { 0 };
	int fd = -1;

	if (!glob(pattern, 0, NULL, &paths) && paths.gl_pathc == 1)
		fd = open(paths.gl_pathv[0], O_RDONLY | O_CLOEXEC);
	globfree(&paths);
	return fd;
}

static int open_regulator(void)
{
	glob_t paths = { 0 };
	char path[256], name[48];
	int fd = -1, handle, found = 0;
	ssize_t count;
	size_t i, length;

	if (glob("/sys/class/regulator/regulator*/name", 0, NULL, &paths))
		return -1;
	for (i = 0; i < paths.gl_pathc; i++) {
		handle = open(paths.gl_pathv[i], O_RDONLY | O_CLOEXEC);
		if (handle < 0)
			continue;
		count = read(handle, name, sizeof(name) - 1);
		close(handle);
		if (count <= 0)
			continue;
		name[count] = '\0';
		name[strcspn(name, "\n")] = '\0';
		if (strcmp(name, "perrier-vdd-mpu"))
			continue;
		if (found++) {
			fd = -1;
			break;
		}
		length = strlen(paths.gl_pathv[i]);
		if (length + 9 > sizeof(path))
			break;
		strcpy(path, paths.gl_pathv[i]);
		strcpy(path + length - 4, "microvolts");
		fd = open(path, O_RDONLY | O_CLOEXEC);
	}
	globfree(&paths);
	return found == 1 ? fd : -1;
}

static int open_sensors(void)
{
	sensors.freq = open("/sys/devices/system/cpu/cpufreq/policy0/cpuinfo_cur_freq",
			    O_RDONLY | O_CLOEXEC);
	sensors.regulator = open_regulator();
	sensors.temperature = open("/sys/class/thermal/thermal_zone0/temp",
				   O_RDONLY | O_CLOEXEC);
	sensors.mpu_mv = open_one("/sys/bus/i2c/devices/3-0041/hwmon/hwmon*/in1_input");
	sensors.mpu_ma = open_one("/sys/bus/i2c/devices/3-0041/hwmon/hwmon*/curr1_input");
	sensors.five_mv = open_one("/sys/bus/i2c/devices/3-0040/hwmon/hwmon*/in3_input");
	sensors.five_ma = open_one("/sys/bus/i2c/devices/3-0040/hwmon/hwmon*/curr3_input");
	return sensors.freq >= 0 && sensors.regulator >= 0 &&
	       sensors.temperature >= 0 && sensors.mpu_mv >= 0 &&
	       sensors.mpu_ma >= 0 && sensors.five_mv >= 0 && sensors.five_ma >= 0;
}

static int sample(long long start_ns, long long *elapsed_ns, long *temperature,
		  uint32_t target_khz, uint32_t target_uv)
{
	struct timespec now;
	long values[7];
	int fds[7] = { sensors.freq, sensors.regulator, sensors.temperature,
		       sensors.mpu_mv, sensors.mpu_ma, sensors.five_mv, sensors.five_ma };
	int i;

	if (clock_gettime(CLOCK_MONOTONIC_RAW, &now))
		return -1;
	*elapsed_ns = nanoseconds(&now) - start_ns;
	for (i = 0; i < 7; i++)
		if (number_fd(fds[i], &values[i]))
			return -1;
	*temperature = values[2];
	printf("SAMPLE %.3f %ld %ld %ld %ld %ld %ld %ld\n",
	       (double)*elapsed_ns / 1000000000.0,
	       values[0], values[1], values[2], values[3], values[4],
	       values[5], values[6]);
	return values[0] == (long)target_khz &&
	       values[1] == (long)target_uv ? 0 : -1;
}

static int parse_count(const char *text, uint32_t *result)
{
	char *end;
	unsigned long value;

	errno = 0;
	value = strtoul(text, &end, 10);
	if (errno || *end || value < 10000ul || value > 400000000ul)
		return -1;
	*result = (uint32_t)value;
	return 0;
}

static int parse_hash(const char *text, uint32_t *result)
{
	char *end;
	unsigned long value;

	errno = 0;
	value = strtoul(text, &end, 16);
	if (errno || end == text || *end || value > UINT32_MAX)
		return -1;
	*result = (uint32_t)value;
	return 0;
}

int main(int argc, char **argv)
{
	const uint32_t seeds[2] = { 0x12345678u, 0x9e3779b9u };
	uint32_t count, expected[2], target_khz, target_uv;
	pthread_barrier_t barrier;
	atomic_int done = 0;
	atomic_int abort = 0;
	struct worker workers[2] = { 0 };
	struct timespec start, pause = { .tv_nsec = SAMPLE_NS };
	long long elapsed, start_ns, final_ms;
	long temperature;
	unsigned int i, samples = 0;
	int failed = 0;

	if ((argc != 3 && argc != 7) || parse_count(argv[2], &count))
		return 2;
	if (!strcmp(argv[1], "ref") && argc == 3) {
		printf("REF %" PRIu32 " %08" PRIx32 " %08" PRIx32 "\n", count,
		       do_work(count, seeds[0], NULL), do_work(count, seeds[1], NULL));
		return 0;
	}
	if (strcmp(argv[1], "run") || argc != 7 ||
	    parse_hash(argv[3], &expected[0]) ||
	    parse_hash(argv[4], &expected[1]) ||
	    parse_count(argv[5], &target_khz) ||
	    parse_count(argv[6], &target_uv) || !open_sensors())
		return 2;
	setvbuf(stdout, NULL, _IOLBF, 0);
	if (pthread_barrier_init(&barrier, NULL, 3))
		return 2;
	for (i = 0; i < 2; i++) {
		workers[i].barrier = &barrier;
		workers[i].done = &done;
		workers[i].abort = &abort;
		workers[i].iterations = count;
		workers[i].seed = seeds[i];
		workers[i].cpu = (int)i;
		if (pthread_create(&workers[i].thread, NULL, worker_main,
				   &workers[i]))
			return 2;
	}
	pthread_barrier_wait(&barrier);
	clock_gettime(CLOCK_MONOTONIC_RAW, &start);
	start_ns = nanoseconds(&start);
	while (1) {
		if (sample(start_ns, &elapsed, &temperature,
			   target_khz, target_uv)) {
			failed = 1;
			break;
		}
		samples++;
		if (temperature >= 75000 || samples >= MAX_SAMPLES)
			failed = 1;
		if (atomic_load_explicit(&done, memory_order_acquire) == 2 || failed)
			break;
		nanosleep(&pause, NULL);
	}
	if (failed)
		atomic_store_explicit(&abort, 1, memory_order_release);
	for (i = 0; i < 2; i++)
		pthread_join(workers[i].thread, NULL);
	final_ms = (workers[0].elapsed_ns > workers[1].elapsed_ns ?
		    workers[0].elapsed_ns : workers[1].elapsed_ns) / 1000000LL;
	printf("RESULT %" PRIu32 " %lld %08" PRIx32 " %08" PRIx32
	       " %lld %lld %u\n", count, final_ms,
	       workers[0].result, workers[1].result,
	       workers[0].elapsed_ns / 1000000LL,
	       workers[1].elapsed_ns / 1000000LL, samples);
	for (i = 0; i < 2; i++)
		if (workers[i].affinity_error || workers[i].result != expected[i])
			failed = 1;
	if (failed) {
		fputs("VERIFY_FAIL\n", stderr);
		return 1;
	}
	puts("VERIFY_PASS");
	return 0;
}

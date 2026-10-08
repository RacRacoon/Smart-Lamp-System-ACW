/* USER CODE BEGIN Header */
/**
 ******************************************************************************
 * @file           : main.c
 * @brief          : Main program body
 ******************************************************************************
 * @attention
 *
 * Copyright (c) 2026 STMicroelectronics.
 * All rights reserved.
 *
 * This software is licensed under terms that can be found in the LICENSE file
 * in the root directory of this software component.
 * If no LICENSE file comes with this software, it is provided AS-IS.
 *
 ******************************************************************************
 */
/* USER CODE END Header */
/* Includes ------------------------------------------------------------------*/
#include "main.h"

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */
#include <stdio.h>
/* USER CODE END Includes */

/* Private typedef -----------------------------------------------------------*/
/* USER CODE BEGIN PTD */

/* USER CODE END PTD */

/* Private define ------------------------------------------------------------*/
/* USER CODE BEGIN PD */

/* USER CODE END PD */

/* Private macro -------------------------------------------------------------*/
/* USER CODE BEGIN PM */

/* USER CODE END PM */

/* Private variables ---------------------------------------------------------*/
ADC_HandleTypeDef hadc1;

I2C_HandleTypeDef hi2c1;

TIM_HandleTypeDef htim3;

UART_HandleTypeDef huart1;
UART_HandleTypeDef huart2;
UART_HandleTypeDef huart3;

/* USER CODE BEGIN PV */
#define RX_RING_SIZE  64u
/* Panjang ini dulu 24 dan diam-diam memotong perintah AT yang panjang. Modem
   Quectel-nya sekarang dilepas, tapi angkanya dibiarkan longgar: satu baris
   JSON telemetri tetap sepanjang itu, dan modul akan kembali begitu kartu SIM
   baru terpasang. */
#define LINE_MAX      200u

/* PB8 dan PB9 adalah LED papan, aktif rendah - pinout NEMA menyebutnya begitu.
   Labelnya di .ioc tertulis GPS_2 dan GPS, dan nama itu menyesatkan: GPS bicara
   lewat USART3 di PB10/PB11, sedangkan PB8/PB9 tidak punya fungsi USART sama
   sekali pada F103. Nama bawaan CubeMX dipakai apa adanya supaya regenerate
   tidak memutus kompilasi, lalu diberi nama yang jujur di sini. */
#define USE_STATUS_LEDS 1
#if USE_STATUS_LEDS
#define HEARTBEAT_Pin        GPS_2_Pin        /* PB8 */
#define HEARTBEAT_GPIO_Port  GPS_2_GPIO_Port
#define LAMPSTATE_Pin        GPS_Pin          /* PB9 */
#define LAMPSTATE_GPIO_Port  GPS_GPIO_Port
/* Aktif rendah: kaki rendah berarti LED menyala. MX_GPIO_Init menahan keduanya
   rendah saat boot, jadi tanpa ini kedua LED menyala terus dan tidak
   memberitahu apa pun. */
#define LED_ON               GPIO_PIN_RESET
#define LED_OFF              GPIO_PIN_SET
#endif

static volatile uint8_t rx_ring[RX_RING_SIZE];
static volatile uint16_t rx_head;   /* written by the ISR only */
static volatile uint16_t rx_tail;   /* written by the main loop only */

static char line[LINE_MAX];
static uint8_t line_len;

/* The GPS receiver sits on USART3 and talks without being asked: a full NMEA
   burst once a second is several hundred bytes arriving back to back, far more
   than a console ever sends, so its ring is the largest of the three. Nothing
   here is printed unless gps_raw is on - the bytes are parsed and thrown away,
   otherwise the console would be unusable. */
#define GPS_RING_SIZE 512u
static volatile uint8_t gp_ring[GPS_RING_SIZE];
static volatile uint16_t gp_head;   /* written by the ISR only */
static volatile uint16_t gp_tail;   /* written by the main loop only */

/* The longest sentence a consumer module emits is GSV at about 80 characters.
   A little headroom, and anything longer is dropped rather than truncated:
   a sentence that overran is a sentence whose checksum will fail anyway. */
#define NMEA_MAX 96u
static char nmea[NMEA_MAX];
static uint8_t nmea_len;
static uint8_t nmea_over;           /* 1 = this sentence overran, skip it */

static uint8_t gps_raw;             /* 1 = echo every good sentence to the console */
static uint8_t gps_fix;             /* GGA quality: 0 none, 1 GPS, 2 DGPS */
static uint8_t gps_sats;           /* satellites used in the fix, from GGA */
static uint8_t gps_view;           /* satellites in view, summed from GSV */
static uint8_t gps_view_acc;       /* the sum being built this cycle */
static int32_t gps_lat_udeg;        /* millionths of a degree, south negative */
static int32_t gps_lon_udeg;        /* millionths of a degree, west negative */
static int32_t gps_alt_dm;          /* metres above the geoid, in decimetres */
static uint32_t gps_pos_tick;       /* HAL_GetTick of the last sentence with a fix */
static uint32_t gps_rx_tick;        /* HAL_GetTick of the last byte received */
static uint32_t gps_sentences;      /* sentences that passed their checksum */
static uint32_t gps_bad;            /* sentences that failed it */
static char gps_utc[9];             /* "hh:mm:ss" straight from the sentence */
static char gps_date[11];           /* "YYYY-MM-DD", from RMC */
static uint32_t gps_baud = 9600u;   /* what almost every module ships at */

static volatile uint8_t ldr_auto;   /* 1 = print the LDR reading once a second */
static uint16_t ldr_tick;           /* loop counter behind ldr_auto */
static uint8_t dim_auto;            /* 1 = the LDR drives the lamp level */
static uint16_t ldr_avg;            /* smoothed LDR reading */
static uint16_t ldr_day = 200u;     /* at or below this raw value: lamp dark */
static uint16_t ldr_night = 2000u;  /* at or above this raw value: lamp full */
static uint16_t dim_level;          /* last requested lamp level, per mille */

#define AUTO_STEP  20u              /* largest level change per second */

#define METER_RING_SIZE 128u

/* PB13 edge timing, all written by EXTI15_10_IRQHandler. */
static volatile uint32_t pf_edges;
static volatile uint32_t pf_cycles;
static volatile uint32_t pf_period_acc;
static volatile uint32_t pf_high_acc;
static volatile uint32_t pf_last_rise;
static volatile uint32_t pf_high_last;
static volatile uint8_t  pf_have_rise;

/* USART1 sniffer ring, fed by USART1_IRQHandler. */
static volatile uint8_t m_ring[METER_RING_SIZE];
static volatile uint16_t m_head;
static volatile uint16_t m_tail;
static uint8_t meter_dump;          /* 1 = print USART1 traffic as hex */
static uint8_t meter_log;           /* 1 = decode and print once a second */
static uint32_t m_bytes;            /* bytes seen on USART1 */
static uint32_t m_frames;           /* frames that passed the checksum */
static uint32_t m_last_tick;        /* HAL tick of the last good frame */

/* The chip sends a frame roughly every 50 ms. Two seconds without one means
   it has stopped - usually because the board lost mains, which also powers
   the meter - and whatever m_good still holds is history, not a reading. */
#define METER_STALE_MS 2000u
/* Voltage scale, volts per unit of the V ratio, x1000. 1.88 is the standard
   HLW8032 module coefficient (a 1.88 MOhm divider over 1 kOhm), and it checks
   out on this board: with mains connected the chip reports a ratio near 116.5,
   and 116.5 x 1.88 = 219 V.

   An earlier default of 564000 was fitted to a ratio of 0.39. That ratio came
   from a voltage input with no AC on it at all: the period counter free-runs
   near 479800 when there is nothing to measure. It only looked like 220 V
   because the constant had been chosen to make it so. */
static uint32_t met_kv = 1880u;

/* Sanity band for the voltage scale. Anything far outside it cannot turn a
   real mains ratio into a mains voltage; it is a typo, a bare command, or a
   value saved under the old, wrong scale, which cfg_load then drops. */
#define MET_KV_MIN  500u
#define MET_KV_MAX  20000u
#define MAINS_MIN_V 50.0             /* below this the voltage input is idle */
#define MAINS_MAX_A 16.0             /* past the socket and relay rating: a bad scale */

/* Current scale, amps per unit of the I ratio, x1e6. It depends on the
   board's current transformer and burden, which are not documented, so it
   is set by measurement with 'ci' rather than guessed. */
static uint32_t met_ki = 1000000u;
static uint8_t met_ki_set;          /* 1 = calibrated, not the default */
#define MET_KI_MIN  1000u
#define MET_KI_MAX  4000000000u

typedef struct {
  uint8_t ok;            /* a voltage reading exists */
  uint8_t has_current;   /* load current is above the chip's threshold */
  uint8_t stale;         /* frames stopped arriving; nothing below is current */
  uint8_t state;
  double  v;             /* volts */
  double  i;             /* amps */
  double  p;             /* watts */
  double  pf;            /* 0..1, negative when unknown */
} meter_t;

/* Settings live in the last 1 KB page of flash. The linker script stops at
   127K so that page belongs to us alone. Bump CFG_VERSION whenever a field
   is added or moved: an older saved copy is then ignored rather than being
   read back through the wrong layout. */
#define CFG_ADDR     0x0801FC00u
#define CFG_MAGIC    0x414D454Eu   /* 'NEMA' */
#define CFG_VERSION  4u         /* 2: tilt reference, 3: current scale, 4: site position */

typedef struct {
  uint32_t magic;
  uint32_t version;
  uint32_t met_kv;
  int32_t  tilt_x;       /* gravity at installation, mg */
  int32_t  tilt_y;
  int32_t  tilt_z;
  uint32_t tilt_set;     /* 1 = the three fields above are valid */
  uint32_t met_ki;       /* v3: current scale, 0 = never calibrated */
  int32_t  site_lat;     /* v4: where this pole stands, millionths of a degree */
  int32_t  site_lon;
  uint32_t site_set;     /* 1 = the two fields above are valid */
  uint32_t check;        /* additive sum of every field above */
} cfg_t;

/* A lamp post does not move, so its position is worth finding once and keeping.
   Held here rather than asked of the GPS every boot: a cold start under a roof
   can take a quarter of an hour, or never finish, and the answer would be the
   same number every time. Once saved, the controller knows where it is before
   the receiver has seen a single satellite - and a later fix that disagrees by
   a wide margin says the pole was moved, or the unit was stolen. */
static int32_t site_lat;
static int32_t site_lon;
static uint8_t site_set;

#define TILT_SAMPLES 32u
static int32_t tilt_ref[3];      /* gravity vector recorded by 'zero', mg */
static uint8_t tilt_ref_set;
static uint8_t accel_ok;         /* accelerometer answered and is configured */
static uint8_t accel_who;

#define HLW_FRAME_LEN 24u
static uint8_t m_frame[HLW_FRAME_LEN];   /* sliding window */
static uint8_t m_good[HLW_FRAME_LEN];    /* last frame that checked out */

static uint16_t dim_duty;           /* current CCR4 value, 0..dim_max */
static uint16_t dim_max;            /* TIM3 ARR, read from the timer at boot */
static uint8_t dim_gamma;           /* 1 = square-law curve on the 'd' command */
static uint8_t dim_invert;          /* 1 = PB1 duty runs opposite to the 'd' request */

/* The 0-10 V stage on the NEMA board is opto-coupled and cannot follow fast
   PWM: at 20 kHz half duty measured 37 mV instead of 5 V. Measured at half
   duty against prescaler: 1 kHz 4.77 V, 200 Hz 5.01 V, 100 Hz 5.01 V. 200 Hz
   is the fastest that still tracks exactly. */
#define DIM_PSC_DEFAULT  99u        /* 72e6 / ((99+1) * 3600) = 200 Hz */
/* USER CODE END PV */

/* Private function prototypes -----------------------------------------------*/
void SystemClock_Config(void);
static void MX_GPIO_Init(void);
static void MX_USART2_UART_Init(void);
static void MX_ADC1_Init(void);
static void MX_USART1_UART_Init(void);
static void MX_TIM3_Init(void);
static void MX_I2C1_Init(void);
static void MX_USART3_UART_Init(void);
/* USER CODE BEGIN PFP */
static uint8_t relay_is_on(void);
static void relay_set(uint8_t on);
static uint16_t ldr_read(void);
static void print_ldr(void);
static uint16_t ldr_to_level(uint16_t raw);
static void auto_service(void);
static void print_pf(void);
static void i2c_scan(void);
static void read_sht30(void);
static void accel_init(void);
static uint8_t accel_sample(int32_t *x, int32_t *y, int32_t *z);
static int16_t tilt_from_ref(int32_t x, int32_t y, int32_t z);
static void tilt_zero(void);
static void read_accel(void);
static uint8_t rtc_read_raw(uint8_t *rx);
static void print_time(void);
static uint8_t meter_fresh(void);
static void meter_decode(meter_t *m);
static void put_fixed(double v, uint8_t decimals);
static void print_mains(void);
static void meter_cal_current(uint32_t milliamps);
static void meter_cal_power(uint32_t watts);
static void read_rtc(void);
static void i2c_dump(uint8_t addr, uint8_t reg);
static void rtc_set(const char *s);
static void rtc_init(void);
static void cfg_load(void);
static void cfg_save(void);
static void meter_set_line(uint32_t baud, uint32_t parity);
static void print_meter_line(void);
static void meter_scan(void);
static void meter_frame_byte(uint8_t b);
static uint32_t be24(const uint8_t *p);
static void print_meter(void);
static void meter_service(void);
static void meter_send_hex(const char *s);
static void dim_set(uint16_t duty);
static void dim_set_permille(uint16_t p);
static void dim_set_prescaler(uint16_t psc);
static void print_dim(void);
static void print_regs(void);
static void print_relay(void);
void hardfault_report(void);
static void print_thresholds(void);
static void print_status(void);
static void print_help(void);
static void handle_line(char *s);
static void rx_service(void);
static void console_init(void);
static void gps_init(void);
static void gps_service(void);
static void gps_set_baud(uint32_t baud);
static void gps_loopback(void);
static void put_udeg(int32_t v);
static void print_gps(void);
static void gps_save_site(void);
static void gps_set_site(const char *s);
static void print_gps_detail(void);
/* USER CODE END PFP */

/* Private user code ---------------------------------------------------------*/
/* USER CODE BEGIN 0 */

/* USER CODE END 0 */

/**
  * @brief  The application entry point.
  * @retval int
  */
int main(void)
{

  /* USER CODE BEGIN 1 */

  /* USER CODE END 1 */

  /* MCU Configuration--------------------------------------------------------*/

  /* Reset of all peripherals, Initializes the Flash interface and the Systick. */
  HAL_Init();

  /* USER CODE BEGIN Init */

  /* USER CODE END Init */

  /* Configure the system clock */
  SystemClock_Config();

  /* USER CODE BEGIN SysInit */

  /* USER CODE END SysInit */

  /* Initialize all configured peripherals */
  MX_GPIO_Init();
  MX_USART2_UART_Init();
  MX_ADC1_Init();
  MX_USART1_UART_Init();
  MX_TIM3_Init();
  MX_I2C1_Init();
  MX_USART3_UART_Init();
  /* USER CODE BEGIN 2 */
  setvbuf(stdout, NULL, _IONBF, 0);

  /* An LDR divider is a high-impedance source. The 1.5 cycles CubeMX emits is
     far too short for the sample-and-hold cap to settle, so re-configure the
     channel here for the longest sampling time (good to roughly 50 kOhm). */
  {
    ADC_ChannelConfTypeDef ldr_ch = {0};
    ldr_ch.Channel = ADC_CHANNEL_8;
    ldr_ch.Rank = ADC_REGULAR_RANK_1;
    ldr_ch.SamplingTime = ADC_SAMPLETIME_239CYCLES_5;
    if (HAL_ADC_ConfigChannel(&hadc1, &ldr_ch) != HAL_OK) {
      Error_Handler();
    }
  }

  /* STM32F1 needs a one-off self-calibration, run with the ADC idle. */
  if (HAL_ADCEx_Calibration_Start(&hadc1) != HAL_OK) {
    Error_Handler();
  }

  /* Dimmer output starts at 0 V. */
  if (HAL_TIM_PWM_Start(&htim3, TIM_CHANNEL_4) != HAL_OK) {
    Error_Handler();
  }
  dim_max = (uint16_t) __HAL_TIM_GET_AUTORELOAD(&htim3);
  if (dim_max == 0u) {
    Error_Handler();          /* an ARR of 0 would leave no usable range */
  }
  __HAL_TIM_SET_PRESCALER(&htim3, DIM_PSC_DEFAULT);

  /* That same stage inverts, so let the firmware invert too and 'd' then runs
     the same way as the lamp: d 0 = dark, d 1000 = full. Boot dark. */
  dim_invert = 1;
  dim_set_permille(0);

  /* Boot state: lamp lit. With the load on the normally-closed contact that is
     also the safe choice: a controller that never comes up leaves the street
     lit, and the coil draws nothing until the lamp is switched off.
     relay_set() drives the lamp-state LED to match, so PB9 needs nothing here. */
  relay_set(1);
#if USE_STATUS_LEDS
  HAL_GPIO_WritePin(HEARTBEAT_GPIO_Port, HEARTBEAT_Pin, LED_OFF);
#endif

  /* The console has to exist before anything prints. */
  console_init();
  gps_init();

  /* PB13 carries the power-factor signal from the meter front end. It has
     no timer capture path, so time both edges in an interrupt instead, and
     let the DWT cycle counter provide the 72 MHz timebase. Pull it down so
     an unconnected pin sits quiet rather than storming the interrupt. */
  CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
  DWT->CYCCNT = 0;
  DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;
  {
    GPIO_InitTypeDef pf_pin = {0};
    pf_pin.Pin = Power_Factor_Pin;
    pf_pin.Mode = GPIO_MODE_IT_RISING_FALLING;
    pf_pin.Pull = GPIO_PULLDOWN;
    HAL_GPIO_Init(Power_Factor_GPIO_Port, &pf_pin);
    HAL_NVIC_SetPriority(EXTI15_10_IRQn, 6, 0);
    HAL_NVIC_EnableIRQ(EXTI15_10_IRQn);
  }

  /* USART1 goes to the power meter. Listen from the start. */
  HAL_NVIC_SetPriority(USART1_IRQn, 5, 0);
  HAL_NVIC_EnableIRQ(USART1_IRQn);

  /* The on-board meter is an HLW8032: it talks unprompted at 4800 8N1 in
     24-byte frames, so open the line at that rate rather than the 115200 the
     generated init picks. meter_set_line() re-arms the RX interrupt itself. */
  meter_set_line(4800u, UART_PARITY_NONE);

  accel_init();
  rtc_init();
  cfg_load();

  printf("\r\n=== APM32F103CB | console USART2 115200 8N1 | PA2=TX PA3=RX ===\r\n");
  printf("=== USART3 -> GPS   USART1 -> power meter ===\r\n");
  print_help();
  print_status();
  printf("> ");
  /* USER CODE END 2 */

  /* Infinite loop */
  /* USER CODE BEGIN WHILE */
	while (1) {
    /* USER CODE END WHILE */

    /* USER CODE BEGIN 3 */
    rx_service();
    meter_service();
    gps_service();

    /* One second of housekeeping every 10 loops of 100 ms. */
    if (++ldr_tick >= 10) {
      ldr_tick = 0;
      if (dim_auto) {
        auto_service();      /* reads the LDR, and logs when ldr_auto is on */
      } else if (ldr_auto) {
        print_ldr();
      }
      if (meter_log) {
        print_meter();
      }
    }

    /* Heartbeat: 5 Hz blink proves the loop is still running. */
#if USE_STATUS_LEDS
    HAL_GPIO_TogglePin(HEARTBEAT_GPIO_Port, HEARTBEAT_Pin);
#endif
    HAL_Delay(100);
  }
  /* USER CODE END 3 */
}

/**
  * @brief System Clock Configuration
  * @retval None
  */
void SystemClock_Config(void)
{
  RCC_OscInitTypeDef RCC_OscInitStruct = {0};
  RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};
  RCC_PeriphCLKInitTypeDef PeriphClkInit = {0};

  /** Initializes the RCC Oscillators according to the specified parameters
  * in the RCC_OscInitTypeDef structure.
  */
  RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSE;
  RCC_OscInitStruct.HSEState = RCC_HSE_ON;
  RCC_OscInitStruct.HSEPredivValue = RCC_HSE_PREDIV_DIV1;
  RCC_OscInitStruct.HSIState = RCC_HSI_ON;
  RCC_OscInitStruct.PLL.PLLState = RCC_PLL_ON;
  RCC_OscInitStruct.PLL.PLLSource = RCC_PLLSOURCE_HSE;
  RCC_OscInitStruct.PLL.PLLMUL = RCC_PLL_MUL9;
  if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK)
  {
    Error_Handler();
  }

  /** Initializes the CPU, AHB and APB buses clocks
  */
  RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_HCLK|RCC_CLOCKTYPE_SYSCLK
                              |RCC_CLOCKTYPE_PCLK1|RCC_CLOCKTYPE_PCLK2;
  RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;
  RCC_ClkInitStruct.AHBCLKDivider = RCC_SYSCLK_DIV1;
  RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV2;
  RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV1;

  if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_2) != HAL_OK)
  {
    Error_Handler();
  }
  PeriphClkInit.PeriphClockSelection = RCC_PERIPHCLK_ADC;
  PeriphClkInit.AdcClockSelection = RCC_ADCPCLK2_DIV6;
  if (HAL_RCCEx_PeriphCLKConfig(&PeriphClkInit) != HAL_OK)
  {
    Error_Handler();
  }
}

/**
  * @brief ADC1 Initialization Function
  * @param None
  * @retval None
  */
static void MX_ADC1_Init(void)
{

  /* USER CODE BEGIN ADC1_Init 0 */

  /* USER CODE END ADC1_Init 0 */

  ADC_ChannelConfTypeDef sConfig = {0};

  /* USER CODE BEGIN ADC1_Init 1 */

  /* USER CODE END ADC1_Init 1 */

  /** Common config
  */
  hadc1.Instance = ADC1;
  hadc1.Init.ScanConvMode = ADC_SCAN_DISABLE;
  hadc1.Init.ContinuousConvMode = DISABLE;
  hadc1.Init.DiscontinuousConvMode = DISABLE;
  hadc1.Init.ExternalTrigConv = ADC_SOFTWARE_START;
  hadc1.Init.DataAlign = ADC_DATAALIGN_RIGHT;
  hadc1.Init.NbrOfConversion = 1;
  if (HAL_ADC_Init(&hadc1) != HAL_OK)
  {
    Error_Handler();
  }

  /** Configure Regular Channel
  */
  sConfig.Channel = ADC_CHANNEL_8;
  sConfig.Rank = ADC_REGULAR_RANK_1;
  sConfig.SamplingTime = ADC_SAMPLETIME_1CYCLE_5;
  if (HAL_ADC_ConfigChannel(&hadc1, &sConfig) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN ADC1_Init 2 */

  /* USER CODE END ADC1_Init 2 */

}

/**
  * @brief I2C1 Initialization Function
  * @param None
  * @retval None
  */
static void MX_I2C1_Init(void)
{

  /* USER CODE BEGIN I2C1_Init 0 */

  /* USER CODE END I2C1_Init 0 */

  /* USER CODE BEGIN I2C1_Init 1 */

  /* USER CODE END I2C1_Init 1 */
  hi2c1.Instance = I2C1;
  hi2c1.Init.ClockSpeed = 100000;
  hi2c1.Init.DutyCycle = I2C_DUTYCYCLE_2;
  hi2c1.Init.OwnAddress1 = 0;
  hi2c1.Init.AddressingMode = I2C_ADDRESSINGMODE_7BIT;
  hi2c1.Init.DualAddressMode = I2C_DUALADDRESS_DISABLE;
  hi2c1.Init.OwnAddress2 = 0;
  hi2c1.Init.GeneralCallMode = I2C_GENERALCALL_DISABLE;
  hi2c1.Init.NoStretchMode = I2C_NOSTRETCH_DISABLE;
  if (HAL_I2C_Init(&hi2c1) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN I2C1_Init 2 */

  /* USER CODE END I2C1_Init 2 */

}

/**
  * @brief TIM3 Initialization Function
  * @param None
  * @retval None
  */
static void MX_TIM3_Init(void)
{

  /* USER CODE BEGIN TIM3_Init 0 */

  /* USER CODE END TIM3_Init 0 */

  TIM_ClockConfigTypeDef sClockSourceConfig = {0};
  TIM_MasterConfigTypeDef sMasterConfig = {0};
  TIM_OC_InitTypeDef sConfigOC = {0};

  /* USER CODE BEGIN TIM3_Init 1 */

  /* USER CODE END TIM3_Init 1 */
  htim3.Instance = TIM3;
  htim3.Init.Prescaler = 0;
  htim3.Init.CounterMode = TIM_COUNTERMODE_UP;
  htim3.Init.Period = 3599;
  htim3.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
  htim3.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_ENABLE;
  if (HAL_TIM_Base_Init(&htim3) != HAL_OK)
  {
    Error_Handler();
  }
  sClockSourceConfig.ClockSource = TIM_CLOCKSOURCE_INTERNAL;
  if (HAL_TIM_ConfigClockSource(&htim3, &sClockSourceConfig) != HAL_OK)
  {
    Error_Handler();
  }
  if (HAL_TIM_PWM_Init(&htim3) != HAL_OK)
  {
    Error_Handler();
  }
  sMasterConfig.MasterOutputTrigger = TIM_TRGO_RESET;
  sMasterConfig.MasterSlaveMode = TIM_MASTERSLAVEMODE_DISABLE;
  if (HAL_TIMEx_MasterConfigSynchronization(&htim3, &sMasterConfig) != HAL_OK)
  {
    Error_Handler();
  }
  sConfigOC.OCMode = TIM_OCMODE_PWM1;
  sConfigOC.Pulse = 0;
  sConfigOC.OCPolarity = TIM_OCPOLARITY_HIGH;
  sConfigOC.OCFastMode = TIM_OCFAST_DISABLE;
  if (HAL_TIM_PWM_ConfigChannel(&htim3, &sConfigOC, TIM_CHANNEL_4) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN TIM3_Init 2 */

  /* USER CODE END TIM3_Init 2 */
  HAL_TIM_MspPostInit(&htim3);

}

/**
  * @brief USART1 Initialization Function
  * @param None
  * @retval None
  */
static void MX_USART1_UART_Init(void)
{

  /* USER CODE BEGIN USART1_Init 0 */

  /* USER CODE END USART1_Init 0 */

  /* USER CODE BEGIN USART1_Init 1 */

  /* USER CODE END USART1_Init 1 */
  huart1.Instance = USART1;
  huart1.Init.BaudRate = 115200;
  huart1.Init.WordLength = UART_WORDLENGTH_8B;
  huart1.Init.StopBits = UART_STOPBITS_1;
  huart1.Init.Parity = UART_PARITY_NONE;
  huart1.Init.Mode = UART_MODE_TX_RX;
  huart1.Init.HwFlowCtl = UART_HWCONTROL_NONE;
  huart1.Init.OverSampling = UART_OVERSAMPLING_16;
  if (HAL_UART_Init(&huart1) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN USART1_Init 2 */

  /* USER CODE END USART1_Init 2 */

}

/**
  * @brief USART2 Initialization Function
  * @param None
  * @retval None
  */
static void MX_USART2_UART_Init(void)
{

  /* USER CODE BEGIN USART2_Init 0 */

  /* USER CODE END USART2_Init 0 */

  /* USER CODE BEGIN USART2_Init 1 */

  /* USER CODE END USART2_Init 1 */
  huart2.Instance = USART2;
  huart2.Init.BaudRate = 115200;
  huart2.Init.WordLength = UART_WORDLENGTH_8B;
  huart2.Init.StopBits = UART_STOPBITS_1;
  huart2.Init.Parity = UART_PARITY_NONE;
  huart2.Init.Mode = UART_MODE_TX_RX;
  huart2.Init.HwFlowCtl = UART_HWCONTROL_NONE;
  huart2.Init.OverSampling = UART_OVERSAMPLING_16;
  if (HAL_UART_Init(&huart2) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN USART2_Init 2 */

  /* USER CODE END USART2_Init 2 */

}

/**
  * @brief USART3 Initialization Function
  * @param None
  * @retval None
  */
static void MX_USART3_UART_Init(void)
{

  /* USER CODE BEGIN USART3_Init 0 */

  /* USER CODE END USART3_Init 0 */

  /* USER CODE BEGIN USART3_Init 1 */

  /* USER CODE END USART3_Init 1 */
  huart3.Instance = USART3;
  huart3.Init.BaudRate = 115200;
  huart3.Init.WordLength = UART_WORDLENGTH_8B;
  huart3.Init.StopBits = UART_STOPBITS_1;
  huart3.Init.Parity = UART_PARITY_NONE;
  huart3.Init.Mode = UART_MODE_TX_RX;
  huart3.Init.HwFlowCtl = UART_HWCONTROL_NONE;
  huart3.Init.OverSampling = UART_OVERSAMPLING_16;
  if (HAL_UART_Init(&huart3) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN USART3_Init 2 */

  /* USER CODE END USART3_Init 2 */

}

/**
  * @brief GPIO Initialization Function
  * @param None
  * @retval None
  */
static void MX_GPIO_Init(void)
{
  GPIO_InitTypeDef GPIO_InitStruct = {0};
  /* USER CODE BEGIN MX_GPIO_Init_1 */

  /* USER CODE END MX_GPIO_Init_1 */

  /* GPIO Ports Clock Enable */
  __HAL_RCC_GPIOC_CLK_ENABLE();
  __HAL_RCC_GPIOD_CLK_ENABLE();
  __HAL_RCC_GPIOA_CLK_ENABLE();
  __HAL_RCC_GPIOB_CLK_ENABLE();

  /*Configure GPIO pin Output Level */
  HAL_GPIO_WritePin(RELAY_GPIO_Port, RELAY_Pin, GPIO_PIN_RESET);

  /*Configure GPIO pin Output Level */
  HAL_GPIO_WritePin(GPIOB, GPS_2_Pin|GPS_Pin, GPIO_PIN_RESET);

  /*Configure GPIO pin : Power_Factor_Pin */
  GPIO_InitStruct.Pin = Power_Factor_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_INPUT;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  HAL_GPIO_Init(Power_Factor_GPIO_Port, &GPIO_InitStruct);

  /*Configure GPIO pin : RELAY_Pin */
  GPIO_InitStruct.Pin = RELAY_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(RELAY_GPIO_Port, &GPIO_InitStruct);

  /*Configure GPIO pins : GPS_2_Pin GPS_Pin */
  GPIO_InitStruct.Pin = GPS_2_Pin|GPS_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);

  /* USER CODE BEGIN MX_GPIO_Init_2 */

  /* USER CODE END MX_GPIO_Init_2 */
}

/* USER CODE BEGIN 4 */
/* The lamp is lit while PA15 is LOW: on this board the load runs through the
   relay's normally-closed contact, so energising the coil breaks the circuit.
   "on" everywhere in this file means the lamp, not the coil. */
#define RELAY_LAMP_ON   GPIO_PIN_RESET
#define RELAY_LAMP_OFF  GPIO_PIN_SET

static uint8_t relay_is_on(void) {
  return (HAL_GPIO_ReadPin(RELAY_GPIO_Port, RELAY_Pin) == RELAY_LAMP_ON) ? 1 : 0;
}

/**
 * @brief Drive the relay and keep the lamp-state LED on PB9 in sync.
 */
static void relay_set(uint8_t on) {
  HAL_GPIO_WritePin(RELAY_GPIO_Port, RELAY_Pin, on ? RELAY_LAMP_ON : RELAY_LAMP_OFF);
#if USE_STATUS_LEDS
  HAL_GPIO_WritePin(LAMPSTATE_GPIO_Port, LAMPSTATE_Pin, on ? LED_ON : LED_OFF);
#endif
}

/**
 * @brief One blocking conversion on PB0 (ADC_CHANNEL_8). Returns 0 on failure.
 */
static uint16_t ldr_read(void) {
  uint16_t raw = 0;

  if (HAL_ADC_Start(&hadc1) == HAL_OK) {
    if (HAL_ADC_PollForConversion(&hadc1, 10) == HAL_OK) {
      raw = (uint16_t) HAL_ADC_GetValue(&hadc1);
    }
    HAL_ADC_Stop(&hadc1);
  }
  return raw;
}

/**
 * @brief Print the LDR reading as counts, millivolts and percent of full scale.
 *
 * Integer maths throughout: newlib-nano's printf has no float support unless
 * the linker is told to pull it in.
 */
static void print_ldr(void) {
  uint16_t raw = ldr_read();
  uint32_t mv = ((uint32_t) raw * 3300u) / 4095u;
  uint32_t pct = ((uint32_t) raw * 100u) / 4095u;

  printf("LIGHT   raw %-4u  %4lu mV  %3lu %%\r\n", (unsigned) raw,
         (unsigned long) mv, (unsigned long) pct);
}

/**
 * @brief Write the PWM compare register. Output compare preload is on, so the
 *        new value only takes effect at the next update event - no runt pulse.
 */
static void dim_set(uint16_t duty) {
  if (duty > dim_max) {
    duty = dim_max;
  }
  dim_duty = duty;
  __HAL_TIM_SET_COMPARE(&htim3, TIM_CHANNEL_4, duty);
}

/**
 * @brief Set the dimmer from a 0..1000 per-mille request.
 *
 * Linear by default: the PWM average, and so the 0-10 V it becomes, tracks the
 * request one to one. A 0-10 V driver already applies its own dimming curve,
 * and stacking a second curve on top crushes the bottom of the range. The
 * square-law option exists for drivers that map voltage straight to current.
 */
static void dim_set_permille(uint16_t p) {
  uint32_t duty;

  if (p > 1000u) {
    p = 1000u;
  }
  dim_level = p;

  if (dim_gamma) {
    duty = (uint32_t) (((uint64_t) p * p * dim_max) / 1000000u);
  } else {
    duty = ((uint32_t) p * dim_max) / 1000u;
  }

  /* Never let a non-zero request round down to fully off. */
  if (duty == 0u && p != 0u) {
    duty = 1u;
  }

  /* The 0-10 V stage on the NEMA board may invert. When it does, the PB1
     duty has to run the other way for 'd' to stay monotonic at the lamp. */
  if (dim_invert) {
    duty = (uint32_t) dim_max - duty;
  }
  dim_set((uint16_t) duty);
}


/**
 * @brief Change the PWM prescaler at runtime, keeping ARR and the duty ratio.
 *
 * Frequency becomes 72 MHz / ((psc + 1) * (ARR + 1)). The prescaler has its own
 * shadow register, so the new value is picked up at the next update event.
 */
static void dim_set_prescaler(uint16_t psc) {
  uint32_t f_mhz = 72000000u / ((uint32_t) psc + 1u);
  uint32_t hz = f_mhz / ((uint32_t) dim_max + 1u);

  __HAL_TIM_SET_PRESCALER(&htim3, psc);
  printf("PWM psc=%u  f=%lu Hz  (period %lu us)\r\n", (unsigned) psc,
         (unsigned long) hz, (unsigned long) (hz ? (1000000u / hz) : 0u));
}

static void print_dim(void) {
  uint32_t permille = ((uint32_t) dim_duty * 1000u) / dim_max;
  uint32_t pb1_mv = ((uint32_t) dim_duty * 3300u) / dim_max;
  uint32_t level = dim_invert ? (1000u - permille) : permille;
  uint32_t hz = (72000000u / ((uint32_t) TIM3->PSC + 1u)) / ((uint32_t) dim_max + 1u);

  printf("LAMP    %lu.%lu %%   %lu mV to driver\r\n",
         (unsigned long) (level / 10u), (unsigned long) (level % 10u),
         (unsigned long) (level * 10u));
  printf("        ccr %u/%u   duty %lu.%lu %%   PB1 avg %lu mV   %lu Hz\r\n",
         (unsigned) dim_duty, (unsigned) dim_max,
         (unsigned long) (permille / 10u), (unsigned long) (permille % 10u),
         (unsigned long) pb1_mv, (unsigned long) hz);
  printf("        curve %s   invert %s\r\n",
         dim_gamma ? "square" : "linear", dim_invert ? "on" : "off");
}


/**
 * @brief Dump the registers that decide whether PWM actually reaches PB1.
 *
 * CR1 bit0 (CEN) must be 1, CCER bit12 (CC4E) must be 1, and the GPIOB CRL
 * nibble for pin 1 must read 0xA or 0xB (alternate function push-pull).
 */
static void print_regs(void) {
  uint32_t crl = GPIOB->CRL;
  uint32_t pb1 = (crl >> 4) & 0xFu;

  printf("TIM3 CR1=0x%04lX CEN=%lu\r\n", (unsigned long) (TIM3->CR1 & 0xFFFFu),
         (unsigned long) (TIM3->CR1 & TIM_CR1_CEN) ? 1UL : 0UL);
  printf("TIM3 PSC=%lu ARR=%lu CCR4=%lu CNT=%lu\r\n",
         (unsigned long) TIM3->PSC, (unsigned long) TIM3->ARR,
         (unsigned long) TIM3->CCR4, (unsigned long) TIM3->CNT);
  printf("TIM3 CCMR2=0x%04lX CCER=0x%04lX CC4E=%lu\r\n",
         (unsigned long) (TIM3->CCMR2 & 0xFFFFu),
         (unsigned long) (TIM3->CCER & 0xFFFFu),
         (unsigned long) (TIM3->CCER & TIM_CCER_CC4E) ? 1UL : 0UL);
  printf("GPIOB CRL=0x%08lX  PB1 nibble=0x%lX (0xA/0xB = AF push-pull)\r\n",
         (unsigned long) crl, (unsigned long) pb1);
}

/**
 * @brief Map a smoothed LDR reading to a lamp level in per mille.
 *
 * Below the day point the lamp stays dark, above the night point it runs full,
 * and it ramps linearly in between. Remember the cell sits on the low leg of
 * the divider, so a larger raw value means darker.
 */
static uint16_t ldr_to_level(uint16_t raw) {
  if (ldr_night <= ldr_day) {
    return 0;                     /* nonsense calibration: stay dark */
  }
  if (raw <= ldr_day) {
    return 0;
  }
  if (raw >= ldr_night) {
    return 1000u;
  }
  return (uint16_t) (((uint32_t) (raw - ldr_day) * 1000u)
                     / (uint32_t) (ldr_night - ldr_day));
}

/**
 * @brief One second of automatic control: read, smooth, and step the lamp.
 *
 * Two brakes sit between the sensor and the lamp. The moving average absorbs
 * headlights and passing shadows, and the slew limit keeps the lamp from
 * chasing its own light: it lights the very cell that drives it, so an
 * immediate correction would oscillate. AUTO_STEP per second means a full
 * sweep takes about a minute, far slower than any real dusk.
 */
static void auto_service(void) {
  uint16_t raw = ldr_read();
  uint16_t target;

  ldr_avg = (uint16_t) (((uint32_t) ldr_avg * 3u + raw) / 4u);
  target = ldr_to_level(ldr_avg);

  if (target > dim_level) {
    uint32_t gap = (uint32_t) target - dim_level;
    dim_set_permille((uint16_t) ((gap > AUTO_STEP) ? (dim_level + AUTO_STEP)
                                                   : target));
  } else if (target < dim_level) {
    uint32_t gap = (uint32_t) dim_level - target;
    dim_set_permille((uint16_t) ((gap > AUTO_STEP) ? (dim_level - AUTO_STEP)
                                                   : target));
  }

  if (ldr_auto) {
    printf("LIGHT   raw %-4u  avg %-4u  target %lu.%lu %%  lamp %lu.%lu %%\r\n",
           (unsigned) raw, (unsigned) ldr_avg,
           (unsigned long) (target / 10u), (unsigned long) (target % 10u),
           (unsigned long) (dim_level / 10u), (unsigned long) (dim_level % 10u));
  }
}

/* cos(angle) x 1000, one entry per degree from 0 to 90. Integer maths only:
   newlib-nano has no float printf unless the linker is told to pull it in. */
static const uint16_t cos_x1000[91] = {
  1000, 1000,  999,  999,  998,  996,  995,  993,  990,  988,
   985,  982,  978,  974,  970,  966,  961,  956,  951,  946,
   940,  934,  927,  921,  914,  906,  899,  891,  883,  875,
   866,  857,  848,  839,  829,  819,  809,  799,  788,  777,
   766,  755,  743,  731,  719,  707,  695,  682,  669,  656,
   643,  629,  616,  602,  588,  574,  559,  545,  530,  515,
   500,  485,  469,  454,  438,  423,  407,  391,  375,  358,
   342,  326,  309,  292,  276,  259,  242,  225,  208,  191,
   174,  156,  139,  122,  105,   87,   70,   52,   35,   17,
     0
};

/**
 * @brief Timestamp both edges of PB13 with the DWT cycle counter.
 *
 * Called from EXTI15_10_IRQHandler. PB13 has no timer input capture path on
 * this part, so the cycle counter stands in for one: it runs at the full
 * 72 MHz, which is 13.9 ns per tick - ample for a 50 Hz mains signal.
 */
void pf_edge(uint8_t level) {
  uint32_t now = DWT->CYCCNT;

  pf_edges++;

  if (level) {
    if (pf_have_rise) {
      pf_period_acc += now - pf_last_rise;
      pf_high_acc += pf_high_last;
      pf_cycles++;
    }
    pf_last_rise = now;
    pf_have_rise = 1;
  } else if (pf_have_rise) {
    pf_high_last = now - pf_last_rise;
  }
}

/**
 * @brief Report what PB13 is actually doing, then clear the accumulators.
 *
 * The last line only means something if PB13 carries the XOR of the voltage
 * and current zero crossings, which is how a lot of cheap power-factor front
 * ends work: duty cycle is then the phase angle over 180 degrees. Confirm the
 * front end before trusting that number.
 */
static void print_pf(void) {
  uint32_t cycles, period, high, edges;
  uint32_t per_ticks, hi_ticks, hz, duty, deg;
  uint8_t level = (HAL_GPIO_ReadPin(Power_Factor_GPIO_Port, Power_Factor_Pin)
                   == GPIO_PIN_SET) ? 1u : 0u;

  __disable_irq();
  cycles = pf_cycles;
  period = pf_period_acc;
  high = pf_high_acc;
  edges = pf_edges;
  pf_cycles = 0;
  pf_period_acc = 0;
  pf_high_acc = 0;
  pf_edges = 0;
  __enable_irq();

  printf("PF pin=%u  edges=%lu  full periods=%lu\r\n", (unsigned) level,
         (unsigned long) edges, (unsigned long) cycles);

  if (cycles == 0u) {
    printf("    no complete period since the last reading\r\n");
    return;
  }

  per_ticks = period / cycles;
  hi_ticks = high / cycles;
  hz = per_ticks ? (72000000u / per_ticks) : 0u;
  duty = per_ticks ? (uint32_t) (((uint64_t) hi_ticks * 1000u) / per_ticks) : 0u;

  printf("    period %lu us (%lu Hz)  high %lu us  duty %lu.%lu%%\r\n",
         (unsigned long) (per_ticks / 72u), (unsigned long) hz,
         (unsigned long) (hi_ticks / 72u),
         (unsigned long) (duty / 10u), (unsigned long) (duty % 10u));

  deg = (duty * 180u) / 1000u;
  if (deg <= 90u) {
    printf("    read as XOR phase: %lu deg, PF ~ 0.%03lu\r\n",
           (unsigned long) deg, (unsigned long) cos_x1000[deg]);
  } else {
    printf("    read as XOR phase: %lu deg, beyond 90 - not a phase signal\r\n",
           (unsigned long) deg);
  }
}

/**
 * @brief Re-open USART1 with a given baud rate and parity.
 *
 * Note the word length: on this part 8 data bits plus a parity bit is
 * UART_WORDLENGTH_9B, not 8B. Asking for 8B with parity would give 7 data
 * bits and silently mangle every frame.
 */
static void meter_set_line(uint32_t baud, uint32_t parity) {
  HAL_UART_DeInit(&huart1);
  huart1.Init.BaudRate = baud;
  huart1.Init.Parity = parity;
  huart1.Init.WordLength = (parity == UART_PARITY_NONE) ? UART_WORDLENGTH_8B
                                                        : UART_WORDLENGTH_9B;
  if (HAL_UART_Init(&huart1) != HAL_OK) {
    printf("USART1 init failed\r\n");
    return;
  }
  __HAL_UART_ENABLE_IT(&huart1, UART_IT_RXNE);
}

static char parity_char(uint32_t parity) {
  if (parity == UART_PARITY_EVEN) {
    return 'E';
  }
  if (parity == UART_PARITY_ODD) {
    return 'O';
  }
  return 'N';
}

static void print_meter_line(void) {
  printf("USART1 %lu 8%c1\r\n", (unsigned long) huart1.Init.BaudRate,
         parity_char(huart1.Init.Parity));
}

/**
 * @brief Try the common meter line settings and report what arrives on each.
 *
 * Only works against a chip that talks unprompted, which most on-board
 * metering front ends do. A request-response device stays silent on every
 * line, and that silence is itself the answer.
 */
static void meter_scan(void) {
  static const uint32_t bauds[5] = { 4800u, 9600u, 19200u, 38400u, 115200u };
  static const uint32_t pars[2] = { UART_PARITY_NONE, UART_PARITY_EVEN };
  uint32_t keep_baud = huart1.Init.BaudRate;
  uint32_t keep_par = huart1.Init.Parity;
  uint8_t bi, pi;

  printf("scanning USART1, 400 ms per line...\r\n");

  for (bi = 0; bi < 5u; bi++) {
    for (pi = 0; pi < 2u; pi++) {
      uint16_t count = 0;
      uint8_t shown = 0;

      meter_set_line(bauds[bi], pars[pi]);
      m_tail = m_head;                    /* drop whatever the switch stirred up */
      HAL_Delay(400);

      printf("  %6lu 8%c1 :", (unsigned long) bauds[bi], parity_char(pars[pi]));
      while (m_tail != m_head) {
        uint8_t b = m_ring[m_tail];
        m_tail = (uint16_t) ((m_tail + 1u) % METER_RING_SIZE);
        count++;
        if (shown < 12u) {
          printf(" %02X", (unsigned) b);
          shown++;
        }
      }
      printf("   (%u bytes)\r\n", (unsigned) count);
    }
  }

  meter_set_line(keep_baud, keep_par);
  printf("scan done, back to ");
  print_meter_line();
}

/**
 * @brief Push one USART1 byte into the sniffer ring. Called from the ISR.
 */
void meter_rx_push(uint8_t b) {
  uint16_t next = (uint16_t) ((m_head + 1u) % METER_RING_SIZE);

  if (next != m_tail) {
    m_ring[m_head] = b;
    m_head = next;
  }
}

/**
 * @brief Print whatever arrived on USART1 as hex, from the main loop.
 */
static void meter_service(void) {
  uint8_t n = 0;

  while (m_tail != m_head) {
    uint8_t b = m_ring[m_tail];
    m_tail = (uint16_t) ((m_tail + 1u) % METER_RING_SIZE);
    m_bytes++;
    meter_frame_byte(b);

    if (meter_dump) {
      if (n == 0u) {
        printf("METER RX:");
      }
      printf(" %02X", (unsigned) b);
      if (++n >= 16u) {
        printf("\r\n");
        n = 0;
      }
    }
  }
  if (n != 0u) {
    printf("\r\n");
  }
}

/**
 * @brief Send a hex string such as "01 04 00 00 00 0A" out of USART1.
 */
static void meter_send_hex(const char *s) {
  uint8_t buf[32];
  uint8_t n = 0;
  int hi = -1;

  while (*s != '\0' && n < sizeof(buf)) {
    int v = -1;

    if (*s >= '0' && *s <= '9') {
      v = *s - '0';
    } else if (*s >= 'a' && *s <= 'f') {
      v = *s - 'a' + 10;
    } else if (*s >= 'A' && *s <= 'F') {
      v = *s - 'A' + 10;
    }

    if (v >= 0) {
      if (hi < 0) {
        hi = v;
      } else {
        buf[n++] = (uint8_t) ((hi << 4) | v);
        hi = -1;
      }
    }
    s++;
  }

  if (n == 0u) {
    printf("nothing to send\r\n");
    return;
  }
  HAL_UART_Transmit(&huart1, buf, n, 100);
  printf("METER TX: %u bytes\r\n", (unsigned) n);
}

/**
 * @brief Feed one byte into the HLW8032 frame assembler.
 *
 * The chip talks unprompted in fixed 24-byte frames, so there is no delimiter
 * to sync on. Instead every byte shifts the window along and a frame is
 * accepted only when byte 1 is the 0x5A check register and the checksum over
 * bytes 2..22 matches byte 23. Two independent conditions is enough to lock on
 * within a frame or two and to stay locked.
 */
static void meter_frame_byte(uint8_t b) {
  uint8_t i;
  uint32_t sum = 0;

  for (i = 0; i < (HLW_FRAME_LEN - 1u); i++) {
    m_frame[i] = m_frame[i + 1u];
  }
  m_frame[HLW_FRAME_LEN - 1u] = b;

  if (m_frame[1] != 0x5Au) {
    return;
  }
  for (i = 2; i <= 22u; i++) {
    sum += m_frame[i];
  }
  if ((uint8_t) (sum & 0xFFu) != m_frame[23]) {
    return;
  }

  for (i = 0; i < HLW_FRAME_LEN; i++) {
    m_good[i] = m_frame[i];
  }
  m_frames++;
  m_last_tick = HAL_GetTick();
}

static uint32_t be24(const uint8_t *p) {
  return ((uint32_t) p[0] << 16) | ((uint32_t) p[1] << 8) | (uint32_t) p[2];
}

/**
 * @brief Decode and print the last good HLW8032 frame.
 *
 * The chip reports ratios, not engineering units: each quantity is a
 * calibration register over a measurement register. The absolute scale still
 * depends on this board's divider and shunt, which are unknown, so the raw
 * ratios are printed as they are and scaled by MET_K_* - all three default to
 * 1000, meaning uncalibrated.
 *
 * Power factor is the one number that needs no external reference beyond those
 * constants: it is active power over apparent power.
 */
static void print_meter(void) {
  uint8_t f[HLW_FRAME_LEN];
  uint8_t i;
  uint32_t vpar, vreg, ipar, ireg, ppar, preg;

  if (m_frames == 0u) {
    printf("METER no valid frame yet (state: %lu bytes seen)\r\n",
           (unsigned long) m_bytes);
    return;
  }

  __disable_irq();
  for (i = 0; i < HLW_FRAME_LEN; i++) {
    f[i] = m_good[i];
  }
  __enable_irq();

  vpar = be24(&f[2]);
  vreg = be24(&f[5]);
  ipar = be24(&f[8]);
  ireg = be24(&f[11]);
  ppar = be24(&f[14]);
  preg = be24(&f[17]);

  printf("METER state=0x%02X  frames=%lu\r\n", (unsigned) f[0],
         (unsigned long) m_frames);
  printf("    raw:");
  for (i = 0; i < HLW_FRAME_LEN; i++) {
    printf(" %02X", (unsigned) f[i]);
  }
  printf("\r\n");
  printf("    Vpar=%lu Vreg=%lu  Ipar=%lu Ireg=%lu  Ppar=%lu Preg=%lu\r\n",
         (unsigned long) vpar, (unsigned long) vreg,
         (unsigned long) ipar, (unsigned long) ireg,
         (unsigned long) ppar, (unsigned long) preg);

  /* The state byte flags an overflowed register: bit 0 voltage, bit 1 current,
     bit 2 power. Below the measuring threshold the register simply never
     completes, which is what an unloaded lamp looks like. */
  if ((f[0] & 0xF0u) == 0xF0u) {
    printf("    overflow:%s%s%s\r\n",
           (f[0] & 0x01u) ? " voltage" : "",
           (f[0] & 0x02u) ? " current" : "",
           (f[0] & 0x04u) ? " power" : "");
  }

  /* Byte 20 toggles bit 7 on every refresh and its low bits count the pulses
     the chip has emitted; bytes 21-22 are its own power-factor register. */
  printf("    update=0x%02X  PFreg=%lu\r\n", (unsigned) f[20],
         (unsigned long) (((uint32_t) f[21] << 8) | (uint32_t) f[22]));

  {
    double rv = (vreg != 0u) ? ((double) vpar / (double) vreg) : 0.0;
    double ri = (ireg != 0u) ? ((double) ipar / (double) ireg) : 0.0;
    double rp = (preg != 0u) ? ((double) ppar / (double) preg) : 0.0;

    printf("    ratios x1000: V %ld   I %ld   P %ld\r\n",
           (long) (rv * 1000.0), (long) (ri * 1000.0), (long) (rp * 1000.0));
    printf("    met_kv %lu   met_ki %lu%s\r\n", (unsigned long) met_kv,
           (unsigned long) met_ki, met_ki_set ? "" : " (default)");

    print_mains();
  }
}

/**
 * @brief Walk the I2C bus and report every address that acknowledges.
 *
 * Addresses below 0x08 and above 0x77 are reserved by the I2C spec, so the
 * sweep skips them. Each address gets two tries: a device busy finishing an
 * earlier conversion can miss the first one.
 */
static void i2c_scan(void) {
  uint8_t addr;
  uint8_t found = 0;

  printf("I2C1 scan 0x08..0x77 (PB6=SCL PB7=SDA)\r\n");

  for (addr = 0x08u; addr <= 0x77u; addr++) {
    if (HAL_I2C_IsDeviceReady(&hi2c1, (uint16_t) (addr << 1), 2, 5) == HAL_OK) {
      printf("  0x%02X ack", (unsigned) addr);
      switch (addr) {
      case 0x44:
      case 0x45:
        printf("   SHT30 temperature/humidity");
        break;
      case 0x32:
        printf("   BL5372 real-time clock");
        break;
      case 0x18:
      case 0x19:
        printf("   accelerometer, LIS3DH family");
        break;
      case 0x1C:
      case 0x1D:
        printf("   accelerometer, MMA8452 or ADXL345 family");
        break;
      case 0x53:
        printf("   accelerometer, ADXL345");
        break;
      case 0x68:
      case 0x69:
        printf("   accelerometer, MPU6050 family, or an RTC");
        break;
      default:
        break;
      }
      printf("\r\n");
      found++;
    }
  }

  if (found == 0u) {
    printf("  nothing answered. Check the pull-up resistors and the wiring:\r\n");
    printf("  STM32 drives SDA and SCL open-drain and has no internal pull-up\r\n");
    printf("  on these pins, so the bus needs 4.7k to 3V3 on each line.\r\n");
  } else {
    printf("  %u device(s)\r\n", (unsigned) found);
  }
}

#define SHT30_ADDR   0x44u
#define RTC_ADDR     0x32u
#define ACCEL_ADDR   0x19u

/**
 * @brief CRC-8 used by the SHT3x family: polynomial 0x31, initial value 0xFF.
 */
static uint8_t sht_crc(const uint8_t *d, uint8_t len) {
  uint8_t crc = 0xFFu;
  uint8_t i, b;

  for (i = 0; i < len; i++) {
    crc ^= d[i];
    for (b = 0; b < 8u; b++) {
      crc = (uint8_t) ((crc & 0x80u) ? (((uint32_t) crc << 1) ^ 0x31u)
                                     : ((uint32_t) crc << 1));
    }
  }
  return crc;
}

/**
 * @brief One high-repeatability SHT30 reading, clock stretching disabled.
 *
 * Clock stretching is avoided on purpose: it would hold SCL low while the
 * sensor converts, blocking every other device on the bus. Instead the command
 * returns immediately and the conversion time is waited out here.
 */
static void read_sht30(void) {
  uint8_t cmd[2] = { 0x24u, 0x00u };   /* single shot, high repeatability */
  uint8_t rx[6];
  int32_t t_milli;
  uint32_t rh_milli;
  uint16_t t_raw, rh_raw;

  if (HAL_I2C_Master_Transmit(&hi2c1, (uint16_t) (SHT30_ADDR << 1), cmd,
                              sizeof(cmd), 50) != HAL_OK) {
    printf("CLIMATE no ack from the SHT30\r\n");
    return;
  }
  HAL_Delay(20);                       /* 15 ms typical at high repeatability */

  if (HAL_I2C_Master_Receive(&hi2c1, (uint16_t) (SHT30_ADDR << 1), rx,
                             sizeof(rx), 50) != HAL_OK) {
    printf("CLIMATE SHT30 sent no data\r\n");
    return;
  }

  if (sht_crc(&rx[0], 2) != rx[2] || sht_crc(&rx[3], 2) != rx[5]) {
    printf("CLIMATE CRC failed: %02X %02X %02X %02X %02X %02X\r\n",
           rx[0], rx[1], rx[2], rx[3], rx[4], rx[5]);
    return;
  }

  t_raw = (uint16_t) (((uint16_t) rx[0] << 8) | rx[1]);
  rh_raw = (uint16_t) (((uint16_t) rx[3] << 8) | rx[4]);

  /* Datasheet: T = -45 + 175 * raw / 65535, RH = 100 * raw / 65535.
     64-bit intermediates keep the multiply from overflowing. */
  t_milli = (int32_t) (((uint64_t) t_raw * 175000u) / 65535u) - 45000;
  rh_milli = (uint32_t) (((uint64_t) rh_raw * 100000u) / 65535u);

  printf("CLIMATE Temperature %ld.%01ld C   Relative Humidity %lu.%01lu %%\r\n",
         (long) (t_milli / 1000), (long) ((t_milli % 1000) / 100),
         (unsigned long) (rh_milli / 1000u),
         (unsigned long) ((rh_milli % 1000u) / 100u));
}

/**
 * @brief Identify the accelerometer and put it in the mode the readings assume.
 *
 * CTRL_REG1 0x57 turns on all three axes at 100 Hz in normal mode, and
 * CTRL_REG4 0x00 selects the +-2 g range. Normal mode gives 10 bits left
 * justified in a 16-bit word, so a reading shifts right by 6 and each count
 * is 4 mg. Done once at boot rather than before every sample, so a burst of
 * samples does not pay the settling time each time.
 */
static void accel_init(void) {
  uint8_t who = 0;
  uint8_t cfg;

  accel_ok = 0u;
  if (HAL_I2C_Mem_Read(&hi2c1, (uint16_t) (ACCEL_ADDR << 1), 0x0Fu,
                       I2C_MEMADD_SIZE_8BIT, &who, 1, 50) != HAL_OK) {
    return;
  }

  cfg = 0x57u;
  (void) HAL_I2C_Mem_Write(&hi2c1, (uint16_t) (ACCEL_ADDR << 1), 0x20u,
                           I2C_MEMADD_SIZE_8BIT, &cfg, 1, 50);
  cfg = 0x00u;
  (void) HAL_I2C_Mem_Write(&hi2c1, (uint16_t) (ACCEL_ADDR << 1), 0x23u,
                           I2C_MEMADD_SIZE_8BIT, &cfg, 1, 50);
  HAL_Delay(20);

  accel_who = who;
  accel_ok = 1u;
}

/**
 * @brief One sample, all three axes in mg. Returns 0 when the read fails.
 */
static uint8_t accel_sample(int32_t *x, int32_t *y, int32_t *z) {
  uint8_t rx[6];

  /* Bit 7 of the register address turns on auto-increment, without which the
     burst would read the same register six times. */
  if (HAL_I2C_Mem_Read(&hi2c1, (uint16_t) (ACCEL_ADDR << 1), 0x28u | 0x80u,
                       I2C_MEMADD_SIZE_8BIT, rx, sizeof(rx), 50) != HAL_OK) {
    return 0u;
  }

  *x = (int32_t) ((int16_t) (((int16_t) (((uint16_t) rx[1] << 8) | rx[0])) >> 6)) * 4;
  *y = (int32_t) ((int16_t) (((int16_t) (((uint16_t) rx[3] << 8) | rx[2])) >> 6)) * 4;
  *z = (int32_t) ((int16_t) (((int16_t) (((uint16_t) rx[5] << 8) | rx[4])) >> 6)) * 4;
  return 1u;
}

/**
 * @brief Angle in degrees between the current gravity vector and the reference.
 *
 * Returns -1 when there is no reference yet. The angle comes from the cross
 * product rather than the dot product: sin changes fastest near zero, where a
 * leaning pole actually sits, while cos is almost flat there and would round
 * one or two degrees away. The dot product still decides which side of 90 the
 * answer falls on.
 *
 * Only ratios of squared lengths are needed, so there is no square root and
 * no arc function: the existing cos table, read as sin(d) = cos(90 - d),
 * turns the ratio back into whole degrees.
 */
static int16_t tilt_from_ref(int32_t x, int32_t y, int32_t z) {
  double ax = (double) x, ay = (double) y, az = (double) z;
  double bx = (double) tilt_ref[0], by = (double) tilt_ref[1], bz = (double) tilt_ref[2];
  double na = ax * ax + ay * ay + az * az;
  double nb = bx * bx + by * by + bz * bz;
  double cx = ay * bz - az * by;
  double cy = az * bx - ax * bz;
  double cz = ax * by - ay * bx;
  double dot = ax * bx + ay * by + az * bz;
  double s2, c2, best = 1e9;
  int16_t deg = 0;
  uint8_t d;

  if (!tilt_ref_set || na <= 0.0 || nb <= 0.0) {
    return -1;
  }
  s2 = (cx * cx + cy * cy + cz * cz) / (na * nb);
  c2 = (dot * dot) / (na * nb);

  /* Each of sin and cos goes flat at one end of the range, so use whichever is
     steep where the answer lies: sin below 45 degrees, cos above. */
  for (d = 0; d <= 90u; d++) {
    double t = (double) cos_x1000[(s2 <= c2) ? (90u - d) : d] / 1000.0;
    double e = t * t - ((s2 <= c2) ? s2 : c2);

    if (e < 0.0) {
      e = -e;
    }
    if (e < best) {
      best = e;
      deg = (int16_t) d;
    }
  }

  if (dot < 0.0) {
    deg = (int16_t) (180 - deg);
  }
  return deg;
}

static void read_accel(void) {
  int32_t x, y, z;
  int16_t deg;

  if (!accel_ok) {
    accel_init();                /* try again: it may have been busy at boot */
  }
  if (!accel_ok) {
    printf("TILT    no ack from the accelerometer\r\n");
    return;
  }
  if (!accel_sample(&x, &y, &z)) {
    printf("TILT    no data from the accelerometer\r\n");
    return;
  }

  deg = tilt_from_ref(x, y, z);
  if (deg < 0) {
    printf("TILT    X %5ld  Y %5ld  Z %5ld mg   no reference yet, type zero\r\n",
           (long) x, (long) y, (long) z);
  } else {
    printf("TILT    X %5ld  Y %5ld  Z %5ld mg   %d deg from reference\r\n",
           (long) x, (long) y, (long) z, (int) deg);
  }
}

/**
 * @brief Record the current direction of gravity as the installed position.
 *
 * 32 samples 12 ms apart, just over one fresh sample each at the 100 Hz rate,
 * so the average spans about 0.4 s and irons out the 4 mg quantisation and any
 * small vibration. The board has to be at rest while this runs.
 */
static void tilt_zero(void) {
  int32_t sx = 0, sy = 0, sz = 0;
  int32_t x, y, z;
  uint8_t i, got = 0;

  if (!accel_ok) {
    accel_init();
  }
  if (!accel_ok) {
    printf("TILT    no ack from the accelerometer, reference not set\r\n");
    return;
  }

  for (i = 0; i < TILT_SAMPLES; i++) {
    HAL_Delay(12);
    if (accel_sample(&x, &y, &z)) {
      sx += x;
      sy += y;
      sz += z;
      got++;
    }
  }

  if (got < (TILT_SAMPLES / 2u)) {
    printf("TILT    only %u of %u samples read, reference not set\r\n",
           (unsigned) got, (unsigned) TILT_SAMPLES);
    return;
  }

  tilt_ref[0] = sx / (int32_t) got;
  tilt_ref[1] = sy / (int32_t) got;
  tilt_ref[2] = sz / (int32_t) got;
  tilt_ref_set = 1u;

  printf("TILT    reference set: X %ld  Y %ld  Z %ld mg   (%u samples)\r\n",
         (long) tilt_ref[0], (long) tilt_ref[1], (long) tilt_ref[2],
         (unsigned) got);
  printf("        type save to keep it across resets\r\n");
}


/**
 * @brief Dump the RTC's first 16 registers and offer a tentative BCD decode.
 *
 * The BL5372 follows the RS5C372 register order, but that has not been
 * verified against this part yet, so the raw bytes are printed alongside the
 * decode. Set a known time and compare before trusting the decoded line.
 */
static uint8_t rtc_read_raw(uint8_t *rx) {
  if (HAL_I2C_Mem_Read(&hi2c1, (uint16_t) (RTC_ADDR << 1), 0x00u,
                       I2C_MEMADD_SIZE_8BIT, rx, 16, 100) == HAL_OK) {
    return 1u;
  }
  return (HAL_I2C_Master_Receive(&hi2c1, (uint16_t) (RTC_ADDR << 1), rx, 16,
                                 100) == HAL_OK) ? 1u : 0u;
}

/**
 * @brief One line of wall-clock time, for the status report.
 */
static void print_time(void) {
  uint8_t rx[16];

  if (!rtc_read_raw(rx)) {
    printf("TIME    RTC not answering\r\n");
    return;
  }
  printf("TIME    20%02X-%02X-%02X %02X:%02X:%02X  weekday %u%s\r\n",
         rx[6], rx[5], rx[4], rx[2] & 0x3Fu, rx[1], rx[0], (unsigned) (rx[3] & 0x07u),
         (rx[15] & 0x10u) ? "   [clock stopped, time not trustworthy]" : "");
}

static uint8_t meter_fresh(void) {
  return (m_frames != 0u && (HAL_GetTick() - m_last_tick) <= METER_STALE_MS)
         ? 1u : 0u;
}

/**
 * @brief Turn the last good HLW8032 frame into engineering units.
 *
 * The chip reports each quantity as a calibration register over a measurement
 * register. Per the datasheet:
 *
 *     V = Vpar / Vreg * Kv
 *     I = Ipar / Ireg * Ki
 *     P = Ppar / Preg * Kv * Ki
 *
 * Kv and Ki depend on this board's voltage divider and current transformer,
 * and live in met_kv and met_ki. Because the power scale is exactly the product
 * of the other two, power factor P / (V * I) cancels both of them out: it comes
 * straight from the three ratios and needs no calibration at all.
 *
 * Below its measuring threshold a register never completes a period and the
 * chip flags it as overflowed in the state byte. That is how "no current"
 * looks, so it is reported as zero rather than as a large number.
 */
static void meter_decode(meter_t *m) {
  uint8_t f[HLW_FRAME_LEN];
  uint8_t i;
  uint32_t vpar, vreg, ipar, ireg, ppar, preg;
  double rv, ri, rp;

  m->ok = 0u;
  m->has_current = 0u;
  m->v = m->i = m->p = 0.0;
  m->pf = -1.0;
  m->stale = 0u;

  if (m_frames == 0u) {
    return;
  }
  if (!meter_fresh()) {
    m->stale = 1u;
    return;
  }

  __disable_irq();
  for (i = 0; i < HLW_FRAME_LEN; i++) {
    f[i] = m_good[i];
  }
  __enable_irq();

  m->state = f[0];
  vpar = be24(&f[2]);
  vreg = be24(&f[5]);
  ipar = be24(&f[8]);
  ireg = be24(&f[11]);
  ppar = be24(&f[14]);
  preg = be24(&f[17]);

  if (vreg == 0u) {
    return;
  }
  rv = (double) vpar / (double) vreg;
  m->v = rv * (double) met_kv / 1000.0;
  m->ok = 1u;

  /* State 0x55 is a clean reading; 0xFx flags overflowed registers, bit 1 for
     current and bit 2 for power. Either one means no usable load current. */
  if ((f[0] & 0xF0u) == 0xF0u && (f[0] & 0x06u) != 0u) {
    return;
  }
  if (ireg == 0u || preg == 0u) {
    return;
  }

  ri = (double) ipar / (double) ireg;
  rp = (double) ppar / (double) preg;

  m->i = ri * (double) met_ki / 1000000.0;
  m->p = rp * ((double) met_kv / 1000.0) * ((double) met_ki / 1000000.0);
  m->pf = rp / (rv * ri);
  m->has_current = 1u;
}

/**
 * @brief Print a value with a fixed number of decimals, without float printf.
 */
static void put_fixed(double v, uint8_t decimals) {
  long scale = 1;
  long n;
  uint8_t d;

  for (d = 0; d < decimals; d++) {
    scale *= 10L;
  }
  if (v < 0.0) {
    printf("-");
    v = -v;
  }
  n = (long) (v * (double) scale + 0.5);
  if (decimals == 0u) {
    printf("%ld", n);
  } else {
    printf("%ld.%0*ld", n / scale, (int) decimals, n % scale);
  }
}

/**
 * @brief One line of mains readings for the status report, each in its unit.
 */
static void print_mains(void) {
  meter_t m;

  meter_decode(&m);
  if (m.stale) {
    printf("MAINS   meter silent for %lu s: check mains to the board\r\n",
           (unsigned long) ((HAL_GetTick() - m_last_tick) / 1000u));
    return;
  }
  if (!m.ok) {
    printf("MAINS   no meter frame yet\r\n");
    return;
  }

  /* With no AC on its voltage input the chip does not flag an overflow: the
     period counter just free-runs and yields a tiny ratio. Anything under a
     few tens of volts is that idle state, not a real mains reading. */
  if (m.v < MAINS_MIN_V) {
    printf("MAINS   no mains voltage on the meter input\r\n");
    return;
  }

  printf("MAINS   ");
  put_fixed(m.v, 1);
  printf(" V");

  if (!m.has_current) {
    printf("   no load current\r\n");
    return;
  }

  printf("   ");
  put_fixed(m.i, 3);
  printf(" A   ");
  put_fixed(m.p, 1);
  printf(" W   ");
  put_fixed(m.v * m.i, 1);
  printf(" VA   PF ");
  if (m.pf < 0.0 || m.pf > 1.05) {
    printf("n/a");                /* registers not settled yet */
  } else {
    put_fixed((m.pf > 1.0) ? 1.0 : m.pf, 2);
  }
  printf("\r\n");

  /* The NEMA socket and the relay are both 10 A parts. A reading far past that
     is not a load, it is a broken current scale - say so instead of letting a
     five-figure wattage sit in the status as if it were real. */
  if (m.i > MAINS_MAX_A) {
    printf("        current scale is wrong: this socket cannot carry that much.\r\n");
    printf("        Recalibrate at full brightness with cw <W> or ci <mA>.\r\n");
  }

  if (!met_ki_set) {
    printf("        A, W and VA use the default current scale. Calibrate with\r\n");
    printf("        ci <milliamps from a clamp meter>. PF needs no calibration.\r\n");
  }
}

/**
 * @brief Set the current scale from a known real power drawn right now.
 *
 * P = Ppar / Preg * Kv * Ki, and Kv is already pinned by the mains voltage, so
 * a known wattage fixes Ki directly. Active power is what the chip's power
 * channel measures, so the lamp's poor power factor at low dimming does not
 * get in the way - no resistive test load is needed.
 *
 * The figure has to be input power from the wall at this exact moment, not
 * the output rating on the driver label: the driver loses roughly a tenth of
 * its input as heat, and may be programmed below its maximum.
 */
static void meter_cal_power(uint32_t watts) {
  uint32_t vpar, vreg, ppar, preg;
  double rv, rp, ki;

  if (watts == 0u) {
    printf("to calibrate: cw <watts drawn from the wall right now>\r\n");
    return;
  }
  if (!meter_fresh()) {
    printf("meter not reporting, cannot calibrate\r\n");
    return;
  }
  if ((m_good[0] & 0xF0u) == 0xF0u && (m_good[0] & 0x06u) != 0u) {
    printf("no load current right now: switch the lamp on first\r\n");
    return;
  }

  vpar = be24(&m_good[2]);
  vreg = be24(&m_good[5]);
  ppar = be24(&m_good[14]);
  preg = be24(&m_good[17]);
  if (vreg == 0u || preg == 0u) {
    printf("meter registers empty, cannot calibrate\r\n");
    return;
  }

  rv = (double) vpar / (double) vreg;
  if (rv * (double) met_kv / 1000.0 < MAINS_MIN_V) {
    printf("no mains voltage on the meter input, cannot calibrate\r\n");
    return;
  }

  rp = (double) ppar / (double) preg;
  ki = (double) watts / (rp * ((double) met_kv / 1000.0));
  if (ki * 1000000.0 < (double) MET_KI_MIN || ki * 1000000.0 > (double) MET_KI_MAX) {
    printf("that would give a current scale out of range, not applied\r\n");
    return;
  }

  met_ki = (uint32_t) (ki * 1000000.0 + 0.5);
  met_ki_set = 1u;
  printf("met_ki = %lu\r\n", (unsigned long) met_ki);
  print_mains();
  printf("        type save to keep it across resets\r\n");
}

/**
 * @brief Set the current scale from a real current reading.
 *
 * Much easier than working out a constant by hand: read the lamp's current on
 * a clamp meter, type it in milliamps, and the firmware divides it by the
 * ratio the chip is reporting at that moment. Power follows automatically.
 */
static void meter_cal_current(uint32_t milliamps) {
  uint32_t ipar, ireg;
  double ri, ki;

  if (milliamps == 0u) {
    printf("met_ki = %lu   (to calibrate: ci <milliamps measured>)\r\n",
           (unsigned long) met_ki);
    return;
  }
  if (!meter_fresh()) {
    printf("meter not reporting, cannot calibrate\r\n");
    return;
  }
  if ((m_good[0] & 0xF0u) == 0xF0u && (m_good[0] & 0x02u) != 0u) {
    printf("no load current right now: switch the lamp on first\r\n");
    return;
  }

  /* The state byte cannot be trusted to say whether there is current: with no
     AC on the board at all the chip has been seen reporting 0x55, "all valid",
     over registers that were simply free-running. A missing mains voltage is
     the one reliable tell, so refuse to learn anything without it. */
  {
    uint32_t vpar = be24(&m_good[2]);
    uint32_t vreg = be24(&m_good[5]);

    if (vreg == 0u
        || ((double) vpar / (double) vreg) * (double) met_kv / 1000.0 < MAINS_MIN_V) {
      printf("no mains voltage on the meter input, cannot calibrate\r\n");
      return;
    }
  }

  ipar = be24(&m_good[8]);
  ireg = be24(&m_good[11]);
  if (ireg == 0u) {
    printf("current register empty, cannot calibrate\r\n");
    return;
  }

  ri = (double) ipar / (double) ireg;
  ki = ((double) milliamps / 1000.0) / ri;
  if (ki * 1000000.0 < (double) MET_KI_MIN || ki * 1000000.0 > (double) MET_KI_MAX) {
    printf("that would give a current scale out of range, not applied\r\n");
    return;
  }

  met_ki = (uint32_t) (ki * 1000000.0 + 0.5);
  met_ki_set = 1u;
  printf("met_ki = %lu\r\n", (unsigned long) met_ki);
  print_mains();
  printf("        type save to keep it across resets\r\n");
}


static void read_rtc(void) {
  uint8_t rx[16];
  uint8_t i;

  if (!rtc_read_raw(rx)) {
    printf("RTC no data\r\n");
    return;
  }

  printf("RTC raw:");
  for (i = 0; i < sizeof(rx); i++) {
    printf(" %02X", rx[i]);
  }
  printf("\r\n");
  /* Printed as hex on purpose: the registers hold BCD, so 0x23 reads as 23.
     Decimal formatting would turn that into 35. */
  printf("    20%02X-%02X-%02X %02X:%02X:%02X  weekday %u%s\r\n",
         rx[6], rx[5], rx[4], rx[2] & 0x3Fu, rx[1], rx[0], (unsigned) (rx[3] & 0x07u),
         (rx[15] & 0x10u) ? "   [oscillator stopped: time not trustworthy]" : "");
}

/**
 * @brief Dump 16 registers from any device on the bus, for probing.
 */
/**
 * @brief Day of week for a Gregorian date, 0 = Sunday.
 *
 * Zeller's congruence. January and February count as months 13 and 14 of the
 * previous year, which is what makes the leap day fall at the end.
 */
static uint8_t day_of_week(uint16_t year, uint8_t month, uint8_t day) {
  uint32_t k, j, h;

  if (month < 3u) {
    month = (uint8_t) (month + 12u);
    year--;
  }
  k = year % 100u;
  j = year / 100u;
  h = ((uint32_t) day + (13u * ((uint32_t) month + 1u)) / 5u + k + (k / 4u)
       + (j / 4u) + (5u * j)) % 7u;

  return (uint8_t) ((h + 6u) % 7u);   /* Zeller counts from Saturday */
}

static uint8_t to_bcd(uint8_t v) {
  return (uint8_t) (((v / 10u) << 4) | (v % 10u));
}

/**
 * @brief Set the RTC from a 12 digit string, YYMMDDhhmmss.
 *
 * The chip addresses registers by number shifted left four bits, so writing
 * from register 0 means a pointer byte of 0x00 followed by the seven date and
 * time bytes in BCD. Control register 2 is cleared afterwards to drop the
 * oscillation-stop flag, which is what marks the stored time as untrustworthy
 * after a power loss.
 */
/**
 * @brief Put the clock into 24-hour mode, checked at every boot.
 *
 * Doing it here as well as in rtc_set means a chip that lost the setting -
 * through a flat backup cell, or through the old rtc_set that zeroed the whole
 * control register - is corrected without anyone having to notice the hour
 * looked wrong first.
 *
 * The hour it already holds cannot be rescued: a 12-hour register with the PM
 * flag set is indistinguishable from a corrupt 24-hour one, so the time is
 * reported as-is and the operator is told to set it once.
 */
static void rtc_init(void) {
  uint8_t rx[16];
  uint8_t ctl;

  if (!rtc_read_raw(rx)) {
    return;                       /* no clock on the bus, nothing to fix */
  }
  if ((rx[15] & 0x20u) != 0u) {
    return;                       /* already counting in 24 hours */
  }

  ctl = (uint8_t) ((rx[15] | 0x20u) & (uint8_t) ~0x10u);
  if (HAL_I2C_Mem_Write(&hi2c1, (uint16_t) (RTC_ADDR << 1), 0xF0u,
                        I2C_MEMADD_SIZE_8BIT, &ctl, 1, 100) != HAL_OK) {
    printf("TIME    RTC would not switch to 24-hour mode\r\n");
    return;
  }
  printf("TIME    RTC was in 12-hour mode, now switched to 24-hour.\r\n");
  printf("        The hour it holds is wrong until you type set YYMMDDhhmmss.\r\n");
}

static void rtc_set(const char *s) {
  uint8_t d[12];
  uint8_t buf[8];
  uint8_t i;
  uint8_t n = 0;
  /* Control2: bit 5 selects 24-hour counting, bit 4 is the stop flag.
     Writing a plain zero here cleared both, which is how the clock ended up
     counting in 12 hours and reporting 36:29 - the hour register carries the
     PM flag in bit 5, and 0x16 | 0x20 reads back as BCD 36. */
  uint8_t ctl = 0x20u;

  while (*s != '\0' && n < 12u) {
    if (*s >= '0' && *s <= '9') {
      d[n++] = (uint8_t) (*s - '0');
    }
    s++;
  }
  if (n != 12u) {
    printf("need 12 digits: set YYMMDDhhmmss\r\n");
    return;
  }

  {
    uint8_t yy = (uint8_t) (d[0] * 10u + d[1]);
    uint8_t mo = (uint8_t) (d[2] * 10u + d[3]);
    uint8_t dd = (uint8_t) (d[4] * 10u + d[5]);
    uint8_t hh = (uint8_t) (d[6] * 10u + d[7]);
    uint8_t mi = (uint8_t) (d[8] * 10u + d[9]);
    uint8_t ss = (uint8_t) (d[10] * 10u + d[11]);

    if (mo < 1u || mo > 12u || dd < 1u || dd > 31u || hh > 23u
        || mi > 59u || ss > 59u) {
      printf("date or time out of range\r\n");
      return;
    }

    buf[0] = to_bcd(ss);
    buf[1] = to_bcd(mi);
    buf[2] = to_bcd(hh);
    buf[3] = day_of_week((uint16_t) (2000u + yy), mo, dd);
    buf[4] = to_bcd(dd);
    buf[5] = to_bcd(mo);
    buf[6] = to_bcd(yy);
  }

  if (HAL_I2C_Mem_Write(&hi2c1, (uint16_t) (RTC_ADDR << 1), 0x00u,
                        I2C_MEMADD_SIZE_8BIT, buf, 7, 100) != HAL_OK) {
    printf("RTC write failed\r\n");
    return;
  }

  /* Register 15, so a pointer byte of 15 * 16 = 0xF0. */
  if (HAL_I2C_Mem_Write(&hi2c1, (uint16_t) (RTC_ADDR << 1), 0xF0u,
                        I2C_MEMADD_SIZE_8BIT, &ctl, 1, 100) != HAL_OK) {
    printf("RTC set, but control2 would not clear\r\n");
  }

  for (i = 0; i < 3u; i++) {
    /* Give the chip a moment, then show what actually landed. */
    HAL_Delay(10);
  }
  read_rtc();
}

/**
 * @brief Additive checksum over every field before `check`.
 */
static uint32_t cfg_sum(const cfg_t *c) {
  const uint32_t *w = (const uint32_t *) c;
  uint32_t s = 0;
  uint8_t i;

  for (i = 0; i < (uint8_t) ((sizeof(cfg_t) / 4u) - 1u); i++) {
    s += w[i];
  }
  return s;
}

/**
 * @brief Load the saved settings, if the last flash page holds a valid copy.
 *
 * A missing or stale copy is not an error: the compiled-in defaults simply
 * stand, which is what a freshly programmed board should do. Each field is
 * range-checked on its own, so one bad value cannot drag the others down.
 *
 * Version 2 copies are still read: v3 only appended the current scale, so the
 * earlier fields sit at the same positions and a board updated in the field
 * keeps its voltage calibration and tilt reference.
 */
static void cfg_load(void) {
  const uint32_t *w = (const uint32_t *) CFG_ADDR;
  uint32_t sum = 0;
  uint8_t fields, i;

  if (w[0] != CFG_MAGIC) {
    return;
  }
  if (w[1] == 4u) {
    fields = 11u;
  } else if (w[1] == 3u) {
    fields = 8u;
  } else if (w[1] == 2u) {
    fields = 7u;
  } else {
    return;
  }

  for (i = 0; i < fields; i++) {
    sum += w[i];
  }
  if (sum != w[fields]) {
    printf("saved config is corrupt, using defaults\r\n");
    return;
  }

  if (w[2] >= MET_KV_MIN && w[2] <= MET_KV_MAX) {
    met_kv = w[2];
  } else {
    printf("saved met_kv %lu is out of range, using the default\r\n",
           (unsigned long) w[2]);
  }

  if (w[6] == 1u) {
    tilt_ref[0] = (int32_t) w[3];
    tilt_ref[1] = (int32_t) w[4];
    tilt_ref[2] = (int32_t) w[5];
    tilt_ref_set = 1u;
  }

  if (fields >= 8u && w[7] >= MET_KI_MIN && w[7] <= MET_KI_MAX) {
    met_ki = w[7];
    met_ki_set = 1u;
  }

  /* Lintang di luar +-90 derajat atau bujur di luar +-180 tidak mungkin, dan
     menandakan salinan yang rusak meski checksum-nya lolos. */
  if (fields >= 11u && w[10] == 1u) {
    int32_t la = (int32_t) w[8];
    int32_t lo = (int32_t) w[9];

    if (la >= -90000000 && la <= 90000000
        && lo >= -180000000 && lo <= 180000000) {
      site_lat = la;
      site_lon = lo;
      site_set = 1u;
    } else {
      printf("saved position is out of range, ignored\r\n");
    }
  }
}

/**
 * @brief Erase the settings page and write the current values into it.
 *
 * The page is the last kilobyte of flash, which the linker script no longer
 * hands out, so nothing else can land there. Flash on this part erases a whole
 * page at a time, so there is no way to update one field in place.
 */
static void cfg_save(void) {
  FLASH_EraseInitTypeDef er = {0};
  uint32_t page_error = 0;
  cfg_t c;
  const uint32_t *w;
  uint8_t i;

  c.magic = CFG_MAGIC;
  c.version = CFG_VERSION;
  c.met_kv = met_kv;
  c.tilt_x = tilt_ref[0];
  c.tilt_y = tilt_ref[1];
  c.tilt_z = tilt_ref[2];
  c.tilt_set = tilt_ref_set ? 1u : 0u;
  c.met_ki = met_ki_set ? met_ki : 0u;
  c.site_lat = site_lat;
  c.site_lon = site_lon;
  c.site_set = site_set ? 1u : 0u;
  c.check = cfg_sum(&c);

  HAL_FLASH_Unlock();

  er.TypeErase = FLASH_TYPEERASE_PAGES;
  er.PageAddress = CFG_ADDR;
  er.NbPages = 1u;
  if (HAL_FLASHEx_Erase(&er, &page_error) != HAL_OK) {
    HAL_FLASH_Lock();
    printf("flash erase failed at 0x%08lX\r\n", (unsigned long) page_error);
    return;
  }

  w = (const uint32_t *) &c;
  for (i = 0; i < (uint8_t) (sizeof(c) / 4u); i++) {
    if (HAL_FLASH_Program(FLASH_TYPEPROGRAM_WORD, CFG_ADDR + (i * 4u),
                          (uint64_t) w[i]) != HAL_OK) {
      HAL_FLASH_Lock();
      printf("flash write failed at word %u\r\n", (unsigned) i);
      return;
    }
  }

  HAL_FLASH_Lock();
  printf("saved: met_kv %lu   met_ki %s", (unsigned long) met_kv,
         met_ki_set ? "calibrated" : "default");
  if (tilt_ref_set) {
    printf("   tilt reference X %ld  Y %ld  Z %ld mg\r\n",
           (long) tilt_ref[0], (long) tilt_ref[1], (long) tilt_ref[2]);
  } else {
    printf("   no tilt reference\r\n");
  }
  if (site_set) {
    printf("        site ");
    put_udeg(site_lat);
    printf("  ");
    put_udeg(site_lon);
    printf("\r\n");
  }
}

static void i2c_dump(uint8_t addr, uint8_t reg) {
  uint8_t rx[16];
  uint8_t i;

  if (HAL_I2C_Mem_Read(&hi2c1, (uint16_t) (addr << 1), reg,
                       I2C_MEMADD_SIZE_8BIT, rx, sizeof(rx), 100) != HAL_OK) {
    printf("0x%02X did not answer\r\n", addr);
    return;
  }
  printf("0x%02X from 0x%02X:", addr, reg);
  for (i = 0; i < sizeof(rx); i++) {
    printf(" %02X", rx[i]);
  }
  printf("\r\n");
}

/**
 * @brief Print the exception frame after a hard fault, then say why.
 *
 * Called from inside HardFault_Handler, so the stacked frame sits a few words
 * above the current stack pointer - how many depends on what the handler's own
 * prologue pushed. Rather than guess, scan upward for a word that looks like a
 * stacked xPSR (bit 24, the Thumb bit, is always set) whose preceding word
 * lands inside flash or RAM. That pair is the PC and xPSR of the faulting
 * instruction.
 *
 * printf() here is safe because the retarget writes to the UART by polling. It
 * needs no interrupts, which is the only reason it still works once everything
 * else has stopped.
 */
void hardfault_report(void) {
  uint32_t sp = __get_MSP();
  uint32_t cfsr = SCB->CFSR;
  uint32_t hfsr = SCB->HFSR;
  uint8_t i;

  printf("\r\n\r\n*** HARD FAULT ***\r\n");
  printf("CFSR=0x%08lX  HFSR=0x%08lX  MSP=0x%08lX\r\n",
         (unsigned long) cfsr, (unsigned long) hfsr, (unsigned long) sp);

  if (cfsr & 0x00000100u) {
    printf("  IBUSERR: jumped to an address holding no code\r\n");
  }
  if (cfsr & 0x00000400u) {
    printf("  IMPRECISERR: a bad data access, address not recorded\r\n");
  }
  if (cfsr & 0x00000200u) {
    printf("  PRECISERR: bad data access, BFAR=0x%08lX\r\n",
           (unsigned long) SCB->BFAR);
  }
  if (cfsr & 0x00010000u) {
    printf("  UNDEFINSTR: undefined instruction\r\n");
  }

  for (i = 0; i < 24u; i++) {
    uint32_t xpsr = *(volatile uint32_t *) (sp + (i * 4u));
    uint32_t pc = (i > 0u) ? *(volatile uint32_t *) (sp + ((i - 1u) * 4u)) : 0u;

    if ((xpsr & 0x01000000u) != 0u && (xpsr & 0x0000FE00u) == 0u
        && pc >= 0x08000000u && pc < 0x08020000u) {
      printf("  faulting PC = 0x%08lX   LR = 0x%08lX\r\n",
             (unsigned long) pc,
             (unsigned long) *(volatile uint32_t *) (sp + ((i - 2u) * 4u)));
      break;
    }
  }
  printf("halted. Reset the board.\r\n");
}

static void print_relay(void) {
  printf("RELAY   %s\r\n", relay_is_on() ? "on" : "off");
}

static void print_thresholds(void) {
  printf("AUTO    %-3s   day <= %-4u   night >= %-4u   step %u/s\r\n",
         dim_auto ? "on" : "off", (unsigned) ldr_day, (unsigned) ldr_night,
         (unsigned) AUTO_STEP);
}

/**
 * @brief Everything the controller can see about the lamp, in one report.
 *
 * Reading it takes a moment: the SHT30 needs 20 ms to convert and each I2C
 * device gets its own timeout, so this is a command to type, not something to
 * run in a loop. The per-second logs exist for that.
 */
static void print_status(void) {
  printf("--- NEMA status ---\r\n");
  print_time();
  print_dim();
  print_ldr();
  read_sht30();
  read_accel();
  print_mains();
  print_gps();
  print_relay();
  print_thresholds();
  printf("LOGS    light %-3s   meter %-3s   meter hex %s\r\n",
         ldr_auto ? "on" : "off", meter_log ? "on" : "off",
         meter_dump ? "on" : "off");
}

/**
 * @brief The command list, grouped the way the printed reference groups it.
 */
static void print_help(void) {
  printf("\r\nA letter with no number asks instead of sets: d, r, b, n, f, c.\r\n");
  printf("Typing d on its own reports the brightness, it does not zero it.\r\n");

  printf("\r\n== LAMP ==\r\n");
  printf("  d <0-1000>      brightness, per mille of full scale\r\n");
  printf("                  refused while auto is on - the LDR wins\r\n");
  printf("  r <0-%u>      brightness, raw compare value\r\n", (unsigned) dim_max);
  printf("  m / m 1 / m 0   LDR drives the lamp: toggle / on / off\r\n");
  printf("  b <raw>         day point: at or below this the lamp is dark\r\n");
  printf("  n <raw>         night point: at or above this the lamp is full\r\n");
  printf("  g               dimmer curve linear / square\r\n");
  printf("  i               invert PB1 duty vs the d request\r\n");
  printf("  1 / 0 / t       relay on / off / toggle\r\n");

  printf("\r\n== READINGS ==\r\n");
  printf("  s               full status: time, lamp, LDR, sensors, mains, GPS\r\n");
  printf("  l               read LDR once\r\n");
  printf("  y               decode the last power meter frame\r\n");
  printf("  w               power-factor pin PB13: period, duty, phase\r\n");
  printf("  a               LDR log 1 Hz on/off\r\n");
  printf("  j               meter decode 1 Hz on/off\r\n");

  printf("\r\n== SETTINGS ==\r\n");
  printf("  c <n>           volts per V-ratio unit, x1000\r\n");
  printf("  ci <mA>         calibrate current from a clamp meter reading\r\n");
  printf("  cw <W>          calibrate current from known wall power, lamp on\r\n");
  printf("  zero            record the tilt reference, board at rest\r\n");
  printf("  save            keep calibration and tilt reference\r\n");
  printf("  set YYMMDDhhmmss  set the RTC, twelve digits\r\n");

  printf("\r\n== GPS ==\r\n");
  printf("  gps             position, satellites and link health\r\n");
  printf("  gps raw         echo every NMEA sentence, on/off\r\n");
  printf("  gps save        record where this pole stands, keep it in flash\r\n");
  printf("  gps set <la> <lo>  type the position instead, same effect\r\n");
  printf("  gps <baud>      reopen USART3 at another baud rate\r\n");
  printf("  gps l           send a line out PB10, count what comes back in\r\n");
  printf("                  proves USART3 with a jumper, but a live GPS\r\n");
  printf("                  also feeds it - read the count, not a verdict\r\n");

  printf("\r\n== MODEM ==\r\n");
  printf("  no AT here      The Quectel answered AT on USART2 until its SIM\r\n");
  printf("                  expired. That port is this console now, so the\r\n");
  printf("                  passthrough is gone - not broken, removed.\r\n");
  printf("                  A new SIM puts the modem back on PA2/PA3, and\r\n");
  printf("                  the console moves off it again.\r\n");

  printf("\r\n== DIAGNOSTICS ==\r\n");
  printf("  z               scan the I2C bus on PB6/PB7\r\n");
  printf("  o <addr> <reg>  dump 16 registers, both in decimal\r\n");
  printf("  k               scan common meter line settings\r\n");
  printf("  u <baud>        set USART1 baud for the power meter\r\n");
  printf("  v               cycle USART1 parity none / even / odd\r\n");
  printf("  x               hex dump of USART1 traffic on/off\r\n");
  printf("  e <hex>         send raw hex bytes out of USART1\r\n");
  printf("  f <psc>         PWM prescaler: f = 72e6 / ((psc+1) * 3600)\r\n");
  printf("  p               dump TIM3 and GPIOB registers\r\n");
  printf("  ? or h          this help\r\n");
}

/**
 * @brief Parse the digits after a command letter. Returns 0 when there are none.
 */
/**
 * @brief Step past one number so a second one can be parsed after it.
 */
/**
 * @brief 1 when a number follows, 0 for a bare command letter.
 *
 * parse_arg() returns 0 both for "0" and for no number at all, and a bare
 * letter must never be read as zero: 'd' on its own would switch the lamp
 * off, 'b' on its own would zero the day threshold. Setters check this first
 * and treat a bare letter as a question instead.
 */
static uint8_t has_arg(const char *s) {
  while (*s == ' ' || *s == '	') {
    s++;
  }
  return (*s >= '0' && *s <= '9') ? 1u : 0u;
}

static const char *skip_arg(const char *s) {
  while (*s == ' ' || *s == '\t') {
    s++;
  }
  while (*s >= '0' && *s <= '9') {
    s++;
  }
  return s;
}

static uint32_t parse_arg(const char *s) {
  uint32_t v = 0;

  while (*s == ' ' || *s == '\t') {
    s++;
  }
  while (*s >= '0' && *s <= '9') {
    v = (v * 10u) + (uint32_t) (*s - '0');
    if (v > 999999999u) {          /* met_kv needs six digits; 16 bits is not enough */
      v = 999999999u;
    }
    s++;
  }
  return v;
}

/**
 * @brief Run one complete command line. Called from the main loop, never the ISR.
 */
static void handle_line(char *s) {
  char c = s[0];

  /* Typing AT used to reach the modem. The passthrough is gone, and without
     this the line would fall through to the switch, which only ever looks at
     the first letter - so AT would silently run 'a' and start the LDR log.
     Say what happened instead of doing something unrelated. */
  if ((s[0] == 'a' || s[0] == 'A') && (s[1] == 't' || s[1] == 'T')) {
    printf("No modem on this board: USART2 is the console now. See ? MODEM.\r\n");
    return;
  }

  /* GPS commands are words, because g on its own is already the dimmer curve.
     They sit before the switch for the same reason set, save and zero do. */
  if ((s[0] == 'g' || s[0] == 'G') && (s[1] == 'p' || s[1] == 'P')
      && (s[2] == 's' || s[2] == 'S')) {
    const char *arg = s + 3;

    while (*arg == ' ' || *arg == '\t') {
      arg++;
    }
    if (arg[0] == 'r' || arg[0] == 'R') {
      gps_raw = gps_raw ? 0u : 1u;
      printf("GPS     raw echo %s\r\n", gps_raw ? "on" : "off");
    } else if ((arg[0] == 's' || arg[0] == 'S')
               && (arg[1] == 'e' || arg[1] == 'E')) {
      gps_set_site(arg + 2);
    } else if (arg[0] == 's' || arg[0] == 'S') {
      gps_save_site();
    } else if (arg[0] == 'l' || arg[0] == 'L') {
      gps_loopback();
    } else if (has_arg(arg)) {
      gps_set_baud(parse_arg(arg));
    } else {
      print_gps_detail();
    }
    return;
  }

  /* One multi-letter command, since every single letter is already taken. */
  if ((s[0] == 'c' || s[0] == 'C') && (s[1] == 'w' || s[1] == 'W')) {
    meter_cal_power(parse_arg(s + 2));
    return;
  }
  if ((s[0] == 'c' || s[0] == 'C') && (s[1] == 'i' || s[1] == 'I')) {
    meter_cal_current(parse_arg(s + 2));
    return;
  }

  if ((s[0] == 's' || s[0] == 'S') && (s[1] == 'e' || s[1] == 'E')
      && (s[2] == 't' || s[2] == 'T')) {
    rtc_set(s + 3);
    return;
  }

  if ((s[0] == 's' || s[0] == 'S') && (s[1] == 'a' || s[1] == 'A')
      && (s[2] == 'v' || s[2] == 'V')) {
    cfg_save();
    return;
  }

  if ((s[0] == 'z' || s[0] == 'Z') && (s[1] == 'e' || s[1] == 'E')
      && (s[2] == 'r' || s[2] == 'R')) {
    tilt_zero();
    return;
  }

  /* Every multi-letter command has been handled above, so a second letter
     here means the line is not a command at all. Without this the switch
     would take the first character and ignore the rest: zzz would scan the
     I2C bus, ss would print the status, and the operator would never learn
     they had mistyped. */
  if ((s[0] != '\0')
      && ((s[1] >= 'a' && s[1] <= 'z') || (s[1] >= 'A' && s[1] <= 'Z'))) {
    printf("unknown cmd '%s', press ? for help\r\n", s);
    return;
  }

  switch (c) {
  case '1':
    relay_set(1);
    print_relay();
    break;
  case '0':
    relay_set(0);
    print_relay();
    break;
  case 't':
  case 'T':
    relay_set(!relay_is_on());
    print_relay();
    break;
  case 'l':
  case 'L':
    print_ldr();
    break;
  case 'a':
  case 'A':
    ldr_auto = !ldr_auto;
    ldr_tick = 0;
    printf("LOGS    light %s\r\n", ldr_auto ? "on" : "off");
    break;
  case 'd':
  case 'D':
    /* LDR yang lebih kuat. Dulu perintah ini diam-diam mematikan mode otomatis,
       jadi siapa pun yang menyetel kecerahan - termasuk dashboard di ujung
       jaringan - bisa melucuti kendali LDR tanpa ada yang memberitahu. Sekarang
       permintaannya ditolak dan alasannya disebutkan; mematikan auto harus
       disengaja lewat m 0. */
    if (has_arg(s + 1)) {
      if (dim_auto) {
        printf("LAMP    auto is on, the LDR sets the level. Type m 0 first.\r\n");
        break;
      }
      dim_set_permille((uint16_t) parse_arg(s + 1));
    }
    print_dim();
    break;
  case 'r':
  case 'R':
    if (has_arg(s + 1)) {
      if (dim_auto) {
        printf("LAMP    auto is on, the LDR sets the level. Type m 0 first.\r\n");
        break;
      }
      dim_set((uint16_t) parse_arg(s + 1));
    }
    print_dim();
    break;
  case 'f':
  case 'F':
    if (has_arg(s + 1)) {
      dim_set_prescaler((uint16_t) parse_arg(s + 1));
    } else {
      print_dim();
    }
    break;
  case 'g':
  case 'G':
    dim_gamma = !dim_gamma;
    print_dim();
    break;
  case 'i':
  case 'I':
    dim_invert = !dim_invert;
    dim_set((uint16_t) ((uint32_t) dim_max - dim_duty));
    print_dim();
    break;
  case 'm':
  case 'M':
    /* Bare m masih menjungkit, seperti yang sudah biasa diketik di konsol.
       m 1 dan m 0 MENYETEL. Perintah dari dashboard datang tanpa tahu keadaan
       papan sekarang, dan menjungkit dari jauh berarti "nyalakan auto" bisa
       justru mematikannya kalau ternyata sudah menyala. */
    if (has_arg(s + 1)) {
      dim_auto = (parse_arg(s + 1) != 0u) ? 1u : 0u;
    } else {
      dim_auto = !dim_auto;
    }
    if (dim_auto) {
      ldr_avg = ldr_read();
    }
    print_thresholds();
    print_ldr();
    break;
  case 'b':
  case 'B':
    if (has_arg(s + 1)) {
      ldr_day = (uint16_t) parse_arg(s + 1);
    }
    print_thresholds();
    break;
  case 'n':
  case 'N':
    if (has_arg(s + 1)) {
      ldr_night = (uint16_t) parse_arg(s + 1);
    }
    print_thresholds();
    break;
  case 'w':
  case 'W':
    print_pf();
    break;
  case 'z':
  case 'Z':
    i2c_scan();
    break;
  case 'o':
  case 'O':
    i2c_dump((uint8_t) parse_arg(s + 1),
             (uint8_t) parse_arg(skip_arg(s + 1)));
    break;
  case 'u':
  case 'U':
    meter_set_line(parse_arg(s + 1), huart1.Init.Parity);
    print_meter_line();
    break;
  case 'v':
  case 'V':
    meter_set_line(huart1.Init.BaudRate,
                   (huart1.Init.Parity == UART_PARITY_NONE)
                       ? UART_PARITY_EVEN
                       : ((huart1.Init.Parity == UART_PARITY_EVEN)
                              ? UART_PARITY_ODD : UART_PARITY_NONE));
    print_meter_line();
    break;
  case 'k':
  case 'K':
    meter_scan();
    break;
  case 'y':
  case 'Y':
    print_meter();
    break;
  case 'c':
  case 'C':
    {
      /* A bare 'c' parses as zero, which would silently zero the voltage
         scale and report 0.0 V forever after. Anything below MET_KV_MIN
         cannot produce a mains reading, so treat it as a query instead. */
      uint32_t k = parse_arg(s + 1);

      if (k < MET_KV_MIN) {
        printf("met_kv = %lu   (to change it: c <%lu-%lu>)\r\n",
               (unsigned long) met_kv, (unsigned long) MET_KV_MIN,
               (unsigned long) MET_KV_MAX);
      } else if (k > MET_KV_MAX) {
        printf("met_kv unchanged: %lu is out of range\r\n", (unsigned long) k);
      } else {
        met_kv = k;
        printf("met_kv = %lu\r\n", (unsigned long) met_kv);
        print_mains();
      }
    }
    break;
  case 'j':
  case 'J':
    meter_log = !meter_log;
    printf("LOGS    meter %s\r\n", meter_log ? "on" : "off");
    break;
  case 'x':
  case 'X':
    meter_dump = !meter_dump;
    printf("LOGS    meter hex %s\r\n", meter_dump ? "on" : "off");
    break;
  case 'e':
  case 'E':
    meter_send_hex(s + 1);
    break;
  case 'p':
  case 'P':
    print_regs();
    break;
  case 's':
  case 'S':
    print_status();
    break;
  case '?':
  case 'h':
  case 'H':
    print_help();
    break;
  default:
    printf("unknown cmd, press ? for help\r\n");
    break;
  }
}

/**
 * @brief Finish the console link that CubeMX opened on USART2 (PA2/PA3).
 *
 * The handle, pins and baud rate come from MX_USART2_UART_Init. Only the
 * receive interrupt is left, and it stays here rather than in NVIC Settings so
 * that CubeMX does not emit a second USART2_IRQHandler beside the one in
 * stm32f1xx_it.c.
 *
 * PA2/PA3 used to carry the Quectel modem. The SIM in it expired, so the
 * module came out and the USB-TTL cable to the PC took its place; the GPS
 * receiver moved into the console's old socket on PB10/PB11.
 */
static void console_init(void) {
  HAL_NVIC_SetPriority(USART2_IRQn, 5, 0);
  HAL_NVIC_EnableIRQ(USART2_IRQn);
  __HAL_UART_ENABLE_IT(&huart2, UART_IT_RXNE);
}

/**
 * @brief Open USART3 for the GPS receiver on PB10/PB11.
 *
 * CubeMX opens USART3 at 115200 because that is its default, but a GPS module
 * ships at 9600 and nothing in the .ioc says otherwise. Re-initialising here
 * rather than changing the .ioc keeps the setting inside a USER CODE block, so
 * the next CubeMX regeneration cannot quietly put it back to 115200.
 *
 * TX is wired but unused: configuring the module (its rate, or which sentences
 * it emits) would need it, and leaving it connected costs nothing.
 */
static void gps_init(void) {
  huart3.Init.BaudRate = gps_baud;
  if (HAL_UART_Init(&huart3) != HAL_OK) {
    printf("GPS     USART3 would not open at %lu baud\r\n",
           (unsigned long) gps_baud);
    return;
  }
  HAL_NVIC_SetPriority(USART3_IRQn, 5, 0);
  HAL_NVIC_EnableIRQ(USART3_IRQn);
  __HAL_UART_ENABLE_IT(&huart3, UART_IT_RXNE);
}

/**
 * @brief Reopen the GPS port at another baud rate, without reflashing.
 *
 * Modules that are not the common 9600 exist, and a wrong rate looks exactly
 * like a dead module: bytes arrive, none of them pass a checksum. Being able
 * to try 4800, 38400 and 115200 from the console settles that in seconds.
 */
static void gps_set_baud(uint32_t baud) {
  if (baud < 1200u || baud > 460800u) {
    printf("GPS     baud out of range, use 1200 to 460800\r\n");
    return;
  }
  gps_baud = baud;
  __HAL_UART_DISABLE_IT(&huart3, UART_IT_RXNE);
  gps_init();
  gps_sentences = 0;
  gps_bad = 0;
  nmea_len = 0;
  nmea_over = 0;
  printf("GPS     USART3 now at %lu baud\r\n", (unsigned long) gps_baud);
}

/**
 * @brief Prove USART3 itself works, by sending a line and reading it back.
 *
 * A GPS receiver cannot be asked to say something on demand, so a silent PB11
 * leaves two very different faults looking identical: a dead port on the board,
 * or a dead module. One jumper from PB10 to PB11 separates them - what comes
 * back has been through the transmitter, both pins and the baud divider.
 *
 * The bytes are counted, not printed: they land in the ring like any others and
 * would otherwise be parsed as a sentence and rejected, inflating the counter
 * that the status line reports.
 */
static void gps_loopback(void) {
  static const char probe[] = "$LOOP,1,2,3*00\r\n";
  uint32_t t0;
  uint16_t seen = 0;

  gp_tail = gp_head;                /* drop whatever was already waiting */
  nmea_len = 0;
  nmea_over = 0;

  if (HAL_UART_Transmit(&huart3, (uint8_t *) probe, 16, 200) != HAL_OK) {
    printf("GPS     loopback: USART3 would not transmit at all\r\n");
    return;
  }

  /* 16 bytes at 9600 baud take 17 ms; 200 ms is room to spare even at 1200. */
  t0 = HAL_GetTick();
  while ((HAL_GetTick() - t0) < 200u) {
    while (gp_tail != gp_head) {
      gp_tail = (uint16_t) ((gp_tail + 1u) % GPS_RING_SIZE);
      seen++;
    }
  }

  if (seen == 0u) {
    printf("GPS     loopback: nothing came back\r\n");
    printf("        With PB10 jumpered to PB11, that means USART3 is dead.\r\n");
    printf("        Without the jumper it proves nothing - fit it first.\r\n");
    return;
  }
  printf("GPS     loopback: %u of 16 bytes returned, USART3 works\r\n",
         (unsigned) seen);
}

/**
 * @brief Push one GPS byte into the ring. Called from the ISR.
 */
void gps_rx_push(uint8_t b) {
  uint16_t next = (uint16_t) ((gp_head + 1u) % GPS_RING_SIZE);

  if (next != gp_tail) {
    gp_ring[gp_head] = b;
    gp_head = next;
  }
}

/**
 * @brief 1 when the trailing *XX matches the XOR of the sentence body.
 *
 * Worth doing rather than trusting the text: at the wrong baud rate a stream
 * of noise still contains plausible-looking commas, and an unchecked parse
 * would then report a position somewhere in the ocean.
 */
static uint8_t nmea_ok(const char *s) {
  uint8_t sum = 0;
  uint8_t i = 1;                    /* skip the leading $ */
  uint8_t hi, lo;

  while (s[i] != '\0' && s[i] != '*') {
    sum ^= (uint8_t) s[i];
    i++;
  }
  if (s[i] != '*' || s[i + 1u] == '\0' || s[i + 2u] == '\0') {
    return 0u;                      /* no checksum at all */
  }
  hi = (uint8_t) s[i + 1u];
  lo = (uint8_t) s[i + 2u];
  hi = (uint8_t) ((hi >= 'a') ? (hi - 'a' + 10)
                             : ((hi >= 'A') ? (hi - 'A' + 10) : (hi - '0')));
  lo = (uint8_t) ((lo >= 'a') ? (lo - 'a' + 10)
                             : ((lo >= 'A') ? (lo - 'A' + 10) : (lo - '0')));
  return (((hi << 4) | lo) == sum) ? 1u : 0u;
}

/**
 * @brief Copy comma-separated field n into out. Field 0 is the sentence name.
 */
static void nmea_field(const char *s, uint8_t n, char *out, uint8_t max) {
  uint8_t field = 0;
  uint8_t o = 0;
  uint8_t i = 0;

  out[0] = '\0';
  while (s[i] != '\0' && s[i] != '*') {
    if (s[i] == ',') {
      field++;
      if (field > n) {
        break;
      }
    } else if (field == n && o < (max - 1u)) {
      out[o++] = s[i];
    }
    i++;
  }
  out[o] = '\0';
}

/**
 * @brief NMEA ddmm.mmmm plus a hemisphere letter, as millionths of a degree.
 *
 * The minutes are held as hundred-thousandths so the divide by 60 stays exact
 * in integers: one minute is 1e6/60 microdegrees, which is not a whole number,
 * but min * 1e5 / 6 is. Six decimals is about 0.11 m at the equator, far finer
 * than the receiver itself.
 */
static int32_t nmea_coord(const char *v, const char *hemi) {
  uint8_t dot = 0;
  uint8_t i = 0;
  int32_t deg = 0;
  int32_t min_1e5 = 0;
  uint8_t digits = 0;
  int32_t out;

  while (v[dot] != '\0' && v[dot] != '.') {
    dot++;
  }
  if (dot < 3u) {
    return 0;                       /* too short to hold degrees and minutes */
  }

  /* Everything before the last two digits of the integer part is degrees:
     two for latitude (ddmm), three for longitude (dddmm). */
  for (i = 0; i < (uint8_t) (dot - 2u); i++) {
    deg = (deg * 10) + (v[i] - '0');
  }
  for (i = (uint8_t) (dot - 2u); i < dot; i++) {
    min_1e5 = (min_1e5 * 10) + (v[i] - '0');
  }
  if (v[dot] == '.') {
    i = (uint8_t) (dot + 1u);
    while (v[i] >= '0' && v[i] <= '9' && digits < 5u) {
      min_1e5 = (min_1e5 * 10) + (v[i] - '0');
      digits++;
      i++;
    }
  }
  while (digits < 5u) {             /* pad out a short fraction */
    min_1e5 *= 10;
    digits++;
  }

  out = (deg * 1000000) + (min_1e5 / 6);
  if (hemi[0] == 'S' || hemi[0] == 'W') {
    out = -out;
  }
  return out;
}

/**
 * @brief Pull the fix out of one checksummed sentence.
 *
 * Only GGA and RMC are read. GGA carries the satellite count and altitude,
 * RMC carries the date, and both carry the position - whichever arrives is
 * used, so the sentence order the module happens to use does not matter.
 */
static void nmea_parse(const char *s) {
  char f[16];
  char h[4];
  const char *id = s + 3;           /* past "$GP", "$GN", "$GL" */

  nmea_field(s, 1, f, sizeof f);
  if (f[0] >= '0' && f[0] <= '9') { /* hhmmss.ss */
    gps_utc[0] = f[0]; gps_utc[1] = f[1]; gps_utc[2] = ':';
    gps_utc[3] = f[2]; gps_utc[4] = f[3]; gps_utc[5] = ':';
    gps_utc[6] = f[4]; gps_utc[7] = f[5]; gps_utc[8] = '\0';
  }

  /* GSV: field 3 is how many satellites that constellation can see. The
     receiver sends one set per constellation each second - GPGSV then BDGSV -
     so they are added up, and the total is published when GGA closes the
     cycle. A receiver that sees nothing at all has no antenna view, which is a
     different problem from one that sees six and cannot lock. */
  if (id[0] == 'G' && id[1] == 'S' && id[2] == 'V') {
    /* GSV dikirim berangkai - empat satelit per kalimat - dan medan 3 mengulang
       TOTAL yang sama di setiap kalimat rangkaian itu. Menjumlahkan tiap kalimat
       menghitungnya berkali-kali: satu rasi dengan 12 satelit dalam 3 kalimat
       terbaca 36. Itu sebabnya status sempat melaporkan 55 satelit terlihat,
       angka yang tidak mungkin dari satu titik di bumi. Medan 2 adalah nomor
       kalimat dalam rangkaian, jadi hanya yang pertama yang dihitung. */
    nmea_field(s, 2, f, sizeof f);
    if (f[0] != '1' || f[1] != '\0') {
      return;
    }
    nmea_field(s, 3, f, sizeof f);
    gps_view_acc = (uint8_t) (gps_view_acc + (uint8_t) parse_arg(f));
    return;
  }

  if (id[0] == 'G' && id[1] == 'G' && id[2] == 'A') {
    gps_view = gps_view_acc;
    gps_view_acc = 0;

    nmea_field(s, 6, f, sizeof f);
    gps_fix = (uint8_t) (f[0] - '0');
    nmea_field(s, 7, f, sizeof f);
    gps_sats = (uint8_t) parse_arg(f);
    nmea_field(s, 9, f, sizeof f);
    gps_alt_dm = (int32_t) parse_arg(f) * 10;   /* whole metres are enough */

    if (gps_fix > 0u) {
      nmea_field(s, 2, f, sizeof f);
      nmea_field(s, 3, h, sizeof h);
      gps_lat_udeg = nmea_coord(f, h);
      nmea_field(s, 4, f, sizeof f);
      nmea_field(s, 5, h, sizeof h);
      gps_lon_udeg = nmea_coord(f, h);
      gps_pos_tick = HAL_GetTick();
    }
    return;
  }

  if (id[0] == 'R' && id[1] == 'M' && id[2] == 'C') {
    nmea_field(s, 2, f, sizeof f);
    if (f[0] != 'A') {
      return;                       /* V: the receiver says do not trust this */
    }
    nmea_field(s, 3, f, sizeof f);
    nmea_field(s, 4, h, sizeof h);
    gps_lat_udeg = nmea_coord(f, h);
    nmea_field(s, 5, f, sizeof f);
    nmea_field(s, 6, h, sizeof h);
    gps_lon_udeg = nmea_coord(f, h);
    gps_pos_tick = HAL_GetTick();

    nmea_field(s, 9, f, sizeof f);  /* ddmmyy */
    if (f[0] >= '0' && f[0] <= '9' && f[5] != '\0') {
      gps_date[0] = '2'; gps_date[1] = '0';
      gps_date[2] = f[4]; gps_date[3] = f[5]; gps_date[4] = '-';
      gps_date[5] = f[2]; gps_date[6] = f[3]; gps_date[7] = '-';
      gps_date[8] = f[0]; gps_date[9] = f[1]; gps_date[10] = '\0';
    }
  }
}

/**
 * @brief Drain the GPS ring and assemble whole sentences, from the main loop.
 *
 * A sentence runs from $ to the line ending. Anything before the first $ is
 * discarded, which is what lets the receiver recover by itself after a reset
 * or a baud change instead of staying permanently out of step.
 */
static void gps_service(void) {
  while (gp_tail != gp_head) {
    uint8_t b = gp_ring[gp_tail];
    gp_tail = (uint16_t) ((gp_tail + 1u) % GPS_RING_SIZE);
    gps_rx_tick = HAL_GetTick();

    if (b == '$') {
      nmea[0] = '$';
      nmea_len = 1;
      nmea_over = 0;
      continue;
    }
    if (nmea_len == 0u) {
      continue;                     /* mid-sentence when we started listening */
    }
    if (b == '\r' || b == '\n') {
      nmea[nmea_len] = '\0';
      if (!nmea_over && nmea_len > 6u) {
        if (nmea_ok(nmea)) {
          gps_sentences++;
          if (gps_raw) {
            printf("%s\r\n", nmea);
          }
          nmea_parse(nmea);
        } else {
          gps_bad++;
        }
      }
      nmea_len = 0;
      continue;
    }
    if (nmea_len < (NMEA_MAX - 1u)) {
      nmea[nmea_len++] = (char) b;
    } else {
      nmea_over = 1;
    }
  }
}

/**
 * @brief Print one signed value held in millionths, as d.dddddd.
 *
 * printf here is newlib-nano without float support, so %f prints nothing at
 * all. The whole and fractional halves are printed separately, and the sign is
 * handled before the split so -0.5 does not come out as 0.-500000.
 */
static void put_udeg(int32_t v) {
  int32_t whole;
  int32_t frac;

  if (v < 0) {
    printf("-");
    v = -v;
  }
  whole = v / 1000000;
  frac = v % 1000000;
  printf("%ld.%06ld", (long) whole, (long) frac);
}

/**
 * @brief Jarak kasar antara dua titik, dalam meter.
 *
 * Satu per sejuta derajat lintang adalah 0,111 m di mana pun. Untuk bujur
 * angkanya menyusut mengikuti kosinus lintang, tapi di -7 derajat kosinusnya
 * 0,992 - selisih di bawah satu persen, jauh lebih kecil daripada ketelitian
 * penerima itu sendiri, jadi diabaikan. Yang dicari di sini bukan ukuran
 * presisi, melainkan jawaban "masih di tiang yang sama atau tidak".
 */
static uint32_t site_distance_m(int32_t lat, int32_t lon) {
  int32_t dlat = lat - site_lat;
  int32_t dlon = lon - site_lon;
  int32_t mlat = (dlat * 111) / 1000;     /* mikroderajat -> meter */
  int32_t mlon = (dlon * 111) / 1000;

  if (mlat < 0) {
    mlat = -mlat;
  }
  if (mlon < 0) {
    mlon = -mlon;
  }

  /* Jarak kota-blok, bukan garis lurus: tanpa akar kuadrat, dan selalu lebih
     besar daripada jarak sebenarnya - condong ke arah aman untuk peringatan. */
  return (uint32_t) (mlat + mlon);
}

/**
 * @brief Baca satu koordinat desimal bertanda, hasilnya per sejuta derajat.
 *
 * parse_arg() tidak bisa dipakai: ia tidak mengenal tanda minus maupun titik
 * desimal, padahal lintang selatan selalu negatif dan enam angka di belakang
 * koma itu justru isinya. Pecahan yang lebih pendek dari enam angka dipadkan,
 * jadi "-7.31" dibaca sebagai -7.310000 dan bukan -7.000031.
 *
 * Mengembalikan 1 kalau ada angka yang terbaca, dan memajukan *p ke sesudahnya.
 */
static uint8_t parse_coord(const char **p, int32_t *out) {
  const char *c = *p;
  int32_t whole = 0;
  int32_t frac = 0;
  uint8_t digits = 0;
  uint8_t any = 0;
  uint8_t neg = 0;

  while (*c == ' ' || *c == '\t' || *c == ',') {
    c++;
  }
  if (*c == '-') {
    neg = 1;
    c++;
  } else if (*c == '+') {
    c++;
  }

  while (*c >= '0' && *c <= '9') {
    whole = (whole * 10) + (*c - '0');
    any = 1;
    c++;
  }
  if (*c == '.') {
    c++;
    while (*c >= '0' && *c <= '9') {
      if (digits < 6u) {
        frac = (frac * 10) + (*c - '0');
        digits++;
      }
      any = 1;
      c++;
    }
  }
  if (!any) {
    return 0u;
  }
  while (digits < 6u) {
    frac *= 10;
    digits++;
  }

  *out = (whole * 1000000) + frac;
  if (neg) {
    *out = -*out;
  }
  *p = c;
  return 1u;
}

/**
 * @brief Tetapkan letak tiang dari angka yang diketik, tanpa menunggu GPS.
 *
 * GPS perlu langit terbuka, dan papan sering sudah terpasang sebelum ada
 * kesempatan membawanya ke luar. Koordinatnya sendiri biasanya sudah diketahui
 * dari peta, jadi tidak ada gunanya menyandera letak tiang pada start dingin
 * yang mungkin tidak pernah selesai di dalam ruangan.
 *
 * Nilai yang diketik diperlakukan sama persis dengan hasil gps save: disimpan
 * ke halaman setelan, dipakai sebagai acuan kalau perangkat berpindah, dan
 * akan ditimpa begitu seseorang menjalankan gps save dengan kunci sungguhan.
 */
static void gps_set_site(const char *s) {
  int32_t la = 0;
  int32_t lo = 0;

  if (!parse_coord(&s, &la) || !parse_coord(&s, &lo)) {
    printf("GPS     need two numbers: gps set -7.314990 112.789501\r\n");
    return;
  }
  if (la < -90000000 || la > 90000000) {
    printf("GPS     latitude out of range, -90 to 90\r\n");
    return;
  }
  if (lo < -180000000 || lo > 180000000) {
    printf("GPS     longitude out of range, -180 to 180\r\n");
    return;
  }

  site_lat = la;
  site_lon = lo;
  site_set = 1u;

  printf("GPS     site set by hand: ");
  put_udeg(site_lat);
  printf("  ");
  put_udeg(site_lon);
  printf("\r\n");
  cfg_save();
}

/**
 * @brief Catat posisi sekarang sebagai letak tiang ini, lalu simpan ke flash.
 */
static void gps_save_site(void) {
  if (gps_fix == 0u || gps_pos_tick == 0u) {
    printf("GPS     no fix yet, nothing to save\r\n");
    return;
  }
  if ((HAL_GetTick() - gps_pos_tick) > 10000u) {
    printf("GPS     last fix is %lu s old, wait for a fresh one\r\n",
           (unsigned long) ((HAL_GetTick() - gps_pos_tick) / 1000u));
    return;
  }

  site_lat = gps_lat_udeg;
  site_lon = gps_lon_udeg;
  site_set = 1u;

  printf("GPS     site recorded: ");
  put_udeg(site_lat);
  printf("  ");
  put_udeg(site_lon);
  printf("   (%u sats)\r\n", (unsigned) gps_sats);
  cfg_save();
}

/**
 * @brief One line about the GPS receiver for the status report.
 */
static void print_gps(void) {
  uint32_t quiet;

  if (gps_rx_tick == 0u) {
    printf("GPS     nothing on PB11 yet (USART3 at %lu baud)\r\n",
           (unsigned long) gps_baud);
    return;
  }

  quiet = (HAL_GetTick() - gps_rx_tick) / 1000u;
  if (quiet > 5u) {
    printf("GPS     silent for %lu s, last seen at %lu baud\r\n",
           (unsigned long) quiet, (unsigned long) gps_baud);
    return;
  }

  /* Bytes but no valid sentence is the signature of a wrong baud rate, so say
     that plainly instead of just reporting no fix. */
  if (gps_sentences == 0u) {
    printf("GPS     bytes arriving but no valid sentence (%lu rejected)\r\n",
           (unsigned long) gps_bad);
    printf("        wrong baud rate? try gps 4800 / 38400 / 115200\r\n");
    return;
  }

  if (gps_fix == 0u) {
    if (gps_view == 0u) {
      printf("GPS     searching, no satellites in view: needs open sky\r\n");
    } else {
      printf("GPS     searching, %u in view, none locked yet\r\n",
             (unsigned) gps_view);
    }
    /* Letak tiang tetap diketahui tanpa kunci - itulah gunanya disimpan. */
    if (site_set) {
      printf("        site ");
      put_udeg(site_lat);
      printf("  ");
      put_udeg(site_lon);
      printf("   (saved)\r\n");
    }
    return;
  }

  printf("GPS     fix %u   %u of %u sats   ", (unsigned) gps_fix,
         (unsigned) gps_sats, (unsigned) gps_view);
  put_udeg(gps_lat_udeg);
  printf("  ");
  put_udeg(gps_lon_udeg);
  printf("   alt %ld m   %s %s UTC   age %lu s\r\n",
         (long) (gps_alt_dm / 10),
         (gps_date[0] != '\0') ? gps_date : "----------",
         (gps_utc[0] != '\0') ? gps_utc : "--:--:--",
         (unsigned long) ((HAL_GetTick() - gps_pos_tick) / 1000u));

  if (site_set) {
    uint32_t d = site_distance_m(gps_lat_udeg, gps_lon_udeg);

    /* 50 m jauh melebihi sebaran penerima murah yang diam di tempat, jadi
       angka sebesar itu berarti tiangnya yang pindah, bukan kuncinya yang
       meleset. */
    printf("        %lu m from the saved site%s\r\n", (unsigned long) d,
           (d > 50u) ? "   MOVED?" : "");
  } else {
    printf("        site not recorded yet, type gps save\r\n");
  }
}

/**
 * @brief Everything the GPS link can tell us, including its own health.
 */
static void print_gps_detail(void) {
  print_gps();
  printf("        USART3 %lu baud   %lu good sentences   %lu rejected\r\n",
         (unsigned long) gps_baud, (unsigned long) gps_sentences,
         (unsigned long) gps_bad);
  printf("        raw echo %s\r\n", gps_raw ? "on" : "off");
  if (site_set) {
    printf("        saved site ");
    put_udeg(site_lat);
    printf("  ");
    put_udeg(site_lon);
    printf("\r\n");
  }
}

/**
 * @brief Push one received byte into the ring. Called from the ISR.
 */
void uart_rx_push(uint8_t b) {
  uint16_t next = (uint16_t) ((rx_head + 1u) % RX_RING_SIZE);

  if (next != rx_tail) {   /* drop the byte rather than overwrite the backlog */
    rx_ring[rx_head] = b;
    rx_head = next;
  }
}

/**
 * @brief Drain the ring, echo what was typed, and run each completed line.
 */
static void rx_service(void) {
  while (rx_tail != rx_head) {
    uint8_t b = rx_ring[rx_tail];
    rx_tail = (uint16_t) ((rx_tail + 1u) % RX_RING_SIZE);

    if (b == '\r' || b == '\n') {
      if (line_len == 0u) {
        continue;               /* swallow the second half of a CRLF pair */
      }
      line[line_len] = '\0';
      line_len = 0;
      printf("\r\n");
      handle_line(line);
      printf("> ");
    } else if (b == '\b' || b == 0x7F) {
      if (line_len > 0u) {
        line_len--;
        printf("\b \b");
      }
    } else if (b >= 0x20 && b < 0x7F) {
      if (line_len < (LINE_MAX - 1u)) {
        line[line_len++] = (char) b;
        printf("%c", (char) b);   /* echo: most terminals do not do it for us */
      }
    }
  }
}

/**
 * @brief Retarget printf()/stdout to the console UART (USART2, PA2/PA3).
 */
int _write(int file, char *ptr, int len) {
  (void) file;
  HAL_UART_Transmit(&huart2, (uint8_t *) ptr, (uint16_t) len, HAL_MAX_DELAY);
  return len;
}
/* USER CODE END 4 */

/**
  * @brief  This function is executed in case of error occurrence.
  * @retval None
  */
void Error_Handler(void)
{
  /* USER CODE BEGIN Error_Handler_Debug */
	/* User can add his own implementation to report the HAL error return state */
	__disable_irq();
	while (1) {
	}
  /* USER CODE END Error_Handler_Debug */
}
#ifdef USE_FULL_ASSERT
/**
  * @brief  Reports the name of the source file and the source line number
  *         where the assert_param error has occurred.
  * @param  file: pointer to the source file name
  * @param  line: assert_param error line source number
  * @retval None
  */
void assert_failed(uint8_t *file, uint32_t line)
{
  /* USER CODE BEGIN 6 */
  /* User can add his own implementation to report the file name and line number,
     ex: printf("Wrong parameters value: file %s on line %d\r\n", file, line) */
  /* USER CODE END 6 */
}
#endif /* USE_FULL_ASSERT */

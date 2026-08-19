# Get Veo3.1 Video Details

## OpenAPI Specification

```yaml
openapi: 3.0.1
info:
  title: ''
  description: ''
  version: 1.0.0
paths:
  /api/v1/veo/record-info:
    get:
      summary: Get Veo3.1 Video Details
      deprecated: false
      description: >

        ::: info[]
          This endpoint is the authoritative source of truth for querying the execution status
          and final results of all Veo 3.1 video tasks, including regular generation,
          video extension, 1080P upgrade, and 4K upgrade tasks.
        :::


        ## Supported Task Types


        This interface supports querying **all Veo 3.1 task types**, including:


        * **Regular Video Generation**  
          Text-to-video, image-to-video, reference/material-based generation
        * **Video Extension**  
          Tasks created via the Extend Veo 3.1 Video interface
        * **1080P Upgrade Tasks**  
          High-definition upgrade tasks created via Get 1080P Video
        * **4K Upgrade Tasks**  
          Ultra-high-definition upgrade tasks created via Get 4K Video

        ## Status Descriptions


        | successFlag | Description |

        |------------|-------------|

        | `0` | Generating — task is currently being processed |

        | `1` | Success — task completed successfully |

        | `2` | Failed — task failed before completion |

        | `3` | Generation Failed — task created successfully but upstream
        generation failed |


        ## Important Notes


        * Query task status using `taskId`

        * You may poll this endpoint periodically until the task completes

        * Callback mechanisms push completion events, but **this endpoint
        remains the final authority**

        * `fallbackFlag` is a **legacy field** and may appear only in older
        regular generation tasks


        ### Response Field Descriptions


        <ParamField path="fallbackFlag" type="boolean">

        Only exists in regular video generation tasks. Whether generated using
        fallback model. `true` means backup model was used, `false` means
        primary model was used. 4K video generation tasks do not include this
        field.

        </ParamField>


        <ParamField path="successFlag" type="integer">

        Task success status identifier:

        - `0`: Generating

        - `1`: Success

        - `2`: Failed

        - `3`: Generation Failed

        </ParamField>


        <ParamField path="response" type="object">

        Detailed result information after task completion. For regular video
        generation tasks, contains video URLs etc.; for 4K video generation
        tasks, contains 4K video URLs and related media information.

        </ParamField>


        ### Task Type Identification


        #### Regular Video Generation Tasks

        The `fallbackFlag` field can identify whether the task used a fallback
        model:

        - `true`: Generated using fallback model, video resolution is 720p

        - `false`: Generated using primary model, may support 1080P (16:9 aspect
        ratio)


        ::: note[]

        Videos generated using the fallback model cannot be upgraded to
        high-definition versions through the Get 1080P Video interface.

        :::


        #### 4K Video Generation Tasks

        - Dedicated tasks for generating 4K ultra-high-definition videos

        - Does not include `fallbackFlag` field

        - Generated videos are in 4K resolution

        - Response includes `mediaIds` and related media information
      operationId: get-veo3-1-video-details
      tags:
        - docs/en/Market/Veo3.1 API
      parameters:
        - name: taskId
          in: query
          description: Task ID
          required: true
          example: veo_task_abcdef123456
          schema:
            type: string
      responses:
        '200':
          description: Request successful
          content:
            application/json:
              schema:
                type: object
                properties:
                  code:
                    type: integer
                    enum:
                      - 200
                      - 400
                      - 401
                      - 404
                      - 422
                      - 451
                      - 455
                      - 500
                    description: >-
                      Response status code


                      - **200**: Success - Request has been processed
                      successfully

                      - **400**: Your prompt was flagged by Website as violating
                      content policies.

                      Only English prompts are supported at this time.

                      Failed to fetch the image. Kindly verify any access limits
                      set by you or your service provider.

                      public error unsafe image upload.

                      - **401**: Unauthorized - Authentication credentials are
                      missing or invalid

                      - **404**: Not Found - The requested resource or endpoint
                      does not exist

                      - **422**: Validation Error - The request parameters
                      failed validation checks.

                      record is null.

                      Temporarily supports records within 14 days.

                      record result data is blank.

                      record status is not success.

                      record result data not exist.

                      record result data is empty.

                      - **451**: Failed to fetch the image. Kindly verify any
                      access limits set by you or your service provider.

                      - **455**: Service Unavailable - System is currently
                      undergoing maintenance

                      - **500**: Server Error - An unexpected error occurred
                      while processing the request.

                      Timeout

                      Internal Error, Please try again later.
                  msg:
                    type: string
                    description: Error message when code != 200
                    examples:
                      - success
                  data:
                    type: object
                    properties:
                      taskId:
                        type: string
                        description: Unique identifier of the video generation task
                        examples:
                          - veo_task_abcdef123456
                      paramJson:
                        type: string
                        description: Request parameters in JSON format
                        examples:
                          - >-
                            {"prompt":"A futuristic city with flying cars at
                            sunset.","waterMark":"KieAI"}
                      completeTime:
                        type: number
                        description: Task completion time
                      response:
                        type: object
                        description: Final result
                        properties:
                          taskId:
                            type: string
                            description: Task ID
                            examples:
                              - veo_task_abcdef123456
                          resultUrls:
                            type: array
                            items:
                              type: string
                            description: Generated video URLs
                            examples:
                              - - http://example.com/video1.mp4
                            nullable: true
                          fullResultUrls:
                            type: array
                            items:
                              type: string
                            description: Full video URLs after extended
                          originUrls:
                            type: array
                            items:
                              type: string
                            description: >-
                              Original video URLs. Only has value when
                              aspect_ratio is not 16:9
                            examples:
                              - - http://example.com/original_video1.mp4
                            nullable: true
                          resolution:
                            type: string
                            description: Video resolution information
                            examples:
                              - 1080p
                        x-apidog-orders:
                          - taskId
                          - resultUrls
                          - fullResultUrls
                          - originUrls
                          - resolution
                        required:
                          - fullResultUrls
                        x-apidog-ignore-properties: []
                      successFlag:
                        type: integer
                        description: |-
                          Generation status flag

                          - **0**: Generating
                          - **1**: Success
                          - **2**: Failed
                          - **3**: Generation Failed
                        enum:
                          - 0
                          - 1
                          - 2
                        examples:
                          - 1
                      errorCode:
                        type: integer
                        description: >-
                          Error code when task fails


                          - **400**: Your prompt was flagged by Website as
                          violating content policies.

                          Only English prompts are supported at this time.

                          Failed to fetch the image. Kindly verify any access
                          limits set by you or your service provider.

                          public error unsafe image upload.

                          - **500**: Internal Error, Please try again later.

                          Internal Error - Timeout

                          - **501**: Failed - Video generation task failed
                        format: int32
                        enum:
                          - 400
                          - 500
                          - 501
                        nullable: true
                      errorMessage:
                        type: string
                        description: Error message when task fails
                        examples:
                          - null
                        nullable: true
                      createTime:
                        type: number
                        description: Task creation time
                      fallbackFlag:
                        type: boolean
                        description: >-
                          Whether generated using fallback model. True means
                          backup model was used, false means primary model was
                          used
                        deprecated: true
                        examples:
                          - false
                    x-apidog-orders:
                      - taskId
                      - paramJson
                      - completeTime
                      - response
                      - successFlag
                      - errorCode
                      - errorMessage
                      - createTime
                      - fallbackFlag
                    x-apidog-ignore-properties: []
                x-apidog-orders:
                  - code
                  - msg
                  - data
                x-apidog-ignore-properties: []
              example:
                code: 200
                msg: success
                data:
                  taskId: veo_task_abcdef123456
                  paramJson: >-
                    {"prompt":"A futuristic city with flying cars at
                    sunset.","waterMark":"KieAI"}
                  completeTime: '2025-06-06 10:30:00'
                  response:
                    taskId: veo_task_abcdef123456
                    resultUrls:
                      - http://example.com/video1.mp4
                    originUrls:
                      - http://example.com/original_video1.mp4
                    fullResultUrls:
                      - http://example.com/full_result.mp4
                    resolution: 1080p
                  successFlag: 1
                  errorCode: null
                  errorMessage: ''
                  createTime: '2025-06-06 10:25:00'
                  fallbackFlag: false
          headers: {}
          x-apidog-name: ''
        '500':
          description: request failed
          content:
            application/json:
              schema:
                type: object
                properties:
                  code:
                    type: integer
                    description: >-
                      Response status code


                      - **200**: Success - Request has been processed
                      successfully

                      - **401**: Unauthorized - Authentication credentials are
                      missing or invalid

                      - **402**: Insufficient Credits - Account does not have
                      enough credits to perform the operation

                      - **404**: Not Found - The requested resource or endpoint
                      does not exist

                      - **408**: Upstream is currently experiencing service
                      issues. No result has been returned for over 10 minutes.

                      - **422**: Validation Error - The request parameters
                      failed validation checks

                      - **429**: Rate Limited - Request limit has been exceeded
                      for this resource

                      - **455**: Service Unavailable - System is currently
                      undergoing maintenance

                      - **500**: Server Error - An unexpected error occurred
                      while processing the request

                      - **501**: Generation Failed - Content generation task
                      failed

                      - **505**: Feature Disabled - The requested feature is
                      currently disabled
                  msg:
                    type: string
                    description: Response message, error description when failed
                  data:
                    type: object
                    properties: {}
                    x-apidog-orders: []
                    x-apidog-ignore-properties: []
                x-apidog-orders:
                  - code
                  - msg
                  - data
                required:
                  - code
                  - msg
                  - data
                x-apidog-ignore-properties: []
              example:
                code: 500
                msg: >-
                  Server Error - An unexpected error occurred while processing
                  the request
                data: null
          headers: {}
          x-apidog-name: 'Error '
      security:
        - BearerAuth: []
          x-apidog:
            schemeGroups:
              - id: kn8M4YUlc5i0A0179ezwx
                schemeIds:
                  - BearerAuth
            required: true
            use:
              id: kn8M4YUlc5i0A0179ezwx
            scopes:
              kn8M4YUlc5i0A0179ezwx:
                BearerAuth: []
      x-apidog-folder: docs/en/Market/Veo3.1 API
      x-apidog-status: released
      x-run-in-apidog: https://app.apidog.com/web/project/1184766/apis/api-28506312-run
components:
  schemas: {}
  securitySchemes:
    BearerAuth:
      type: bearer
      scheme: bearer
      bearerFormat: API Key
      description: |-
        所有 API 都需要通过 Bearer Token 进行身份验证。

        获取 API Key：
        1. 访问 [API Key 管理页面](https://kie.ai/api-key) 获取您的 API Key

        使用方法：
        在请求头中添加：
        Authorization: Bearer YOUR_API_KEY

        注意事项：
        - 请妥善保管您的 API Key，切勿泄露给他人
        - 若怀疑 API Key 泄露，请立即在管理页面重置
servers:
  - url: https://api.kie.ai
    description: 正式环境
security:
  - BearerAuth: []
    x-apidog:
      schemeGroups:
        - id: kn8M4YUlc5i0A0179ezwx
          schemeIds:
            - BearerAuth
      required: true
      use:
        id: kn8M4YUlc5i0A0179ezwx
      scopes:
        kn8M4YUlc5i0A0179ezwx:
          BearerAuth: []

```
# Get 4K Video

## OpenAPI Specification

```yaml
openapi: 3.0.1
info:
  title: ''
  description: ''
  version: 1.0.0
paths:
  /api/v1/veo/get-4k-video:
    post:
      summary: Get 4K Video
      deprecated: false
      description: >-
        ::: info[]
          Get the ultra-high-definition 4K version of a Veo 3.1 video generation task.
        :::


        ::: note[]
          Legacy note: If a task was generated via a deprecated fallback path, this endpoint may not apply.
        :::


        ### Usage Instructions


        * **API method difference**
          * **1080P** uses **GET**: `/api/v1/veo/get-1080p-video`
          * **4K** uses **POST**: `/api/v1/veo/get-4k-video`
        * **Credit consumption**
          * 4K requires **additional credits**.
          * The extra cost is approximately **equivalent to 2× “Fast mode” video generations** (see [pricing details](https://kie.ai/pricing) for the latest).
        * **Supported aspect ratios**
          * Both **16:9** and **9:16** tasks support upgrading to **1080P** and **4K**.
        * **Processing time**
          * 4K generation requires significant extra processing time — typically **~5–10 minutes** depending on load.
        * If the 4K video is not ready yet, the endpoint may return a non-200
        code. Wait and retry (recommended interval: **30s+**) until the result
        is available.


        ::: tip[]
          For production use, we recommend using `callBackUrl` to receive automatic notifications when 4K generation completes, rather than polling frequently.
        :::


        ## Callbacks


        After submitting a 4K video generation task, use the unified callback
        mechanism to receive generation completion notifications:


        <Card title="4K Video Generation Callbacks" icon="bell"
        href="/veo3-api/get-veo-3-4k-video-callbacks">
          Learn how to configure and handle 4K video generation callback notifications
        </Card>



        ## Error Responses


        When submitting repeated requests for the same task ID, the system
        returns a `422` status code with specific error details:


        <Tabs>
          <TabItem value="processing" label="4K Video Processing">
            ```json
            {
              "code": 422,
              "msg": "4k is processing. It should be ready in 5-10 minutes. Please check back shortly.",
              "data": {
                "taskId": "veo_task_example123",
                "resultUrls": null,
                "imageUrls": null
              }
            }
            ```
          </TabItem>
          <TabItem value="generated" label="4K Video Already Generated">
            ```json
            {
              "code": 422,
              "msg": "The video has been generated successfully",
              "data": {
                "taskId": "veo_task_example123",
                "resultUrls": [
                  "https://tempfile.aiquickdraw.com/v/example_task_1234567890.mp4"
                ],
                "imageUrls": [
                  "https://tempfile.aiquickdraw.com/v/example_task_1234567890.jpg"
                ]
              }
            }
            ```
          </TabItem>
        </Tabs>
      operationId: get-veo3-1-4k-video
      tags:
        - docs/en/Market/Veo3.1 API
      parameters: []
      requestBody:
        content:
          application/json:
            schema:
              type: object
              required:
                - taskId
              properties:
                taskId:
                  type: string
                  description: Task ID
                  examples:
                    - veo_task_abcdef123456
                index:
                  type: integer
                  description: video index
                  default: 0
                  examples:
                    - 0
                callBackUrl:
                  type: string
                  format: uri
                  description: >-
                    The URL to receive 4K video generation task completion
                    updates. Optional but recommended for production use.


                    - System will POST task status and results to this URL when
                    4K video generation completes

                    - Callback includes generated video URLs, media IDs, and
                    related information

                    - Your callback endpoint should accept POST requests with
                    JSON payload containing results

                    - Alternatively, use the Get Video Details endpoint to poll
                    task status

                    - To ensure callback security, see [Webhook Verification
                    Guide](/common-api/webhook-verification) for signature
                    verification implementation
                  examples:
                    - http://your-callback-url.com/4k-callback
              x-apidog-orders:
                - taskId
                - index
                - callBackUrl
              x-apidog-ignore-properties: []
            example:
              taskId: veo_task_abcdef123456
              index: 0
              callBackUrl: http://your-callback-url.com/4k-callback
      responses:
        '200':
          description: Request successful
          content:
            application/json:
              schema:
                type: object
                properties:
                  code:
                    type: integer
                    enum:
                      - 200
                      - 401
                      - 404
                      - 422
                      - 429
                      - 451
                      - 455
                      - 500
                    description: >-
                      Response status code


                      - **200**: Success - Request has been processed
                      successfully

                      - **401**: Unauthorized - Authentication credentials are
                      missing or invalid

                      - **404**: Not Found - The requested resource or endpoint
                      does not exist

                      - **422**: Validation Error - The request parameters
                      failed validation checks.

                      record is null.

                      Temporarily supports records within 14 days.

                      record result data is blank.

                      record status is not success.

                      record result data not exist.

                      record result data is empty.

                      - **429**: Rate Limited - Request limit has been exceeded
                      for this resource

                      - **451**: Failed to fetch the image. Kindly verify any
                      access limits set by you or your service provider.

                      - **455**: Service Unavailable - System is currently
                      undergoing maintenance

                      - **500**: Server Error - An unexpected error occurred
                      while processing the request
                  msg:
                    type: string
                    description: Error message when code != 200
                    examples:
                      - success
                  data:
                    type: object
                    properties:
                      taskId:
                        type: string
                        description: >-
                          Task ID, can be used with Get Video Details endpoint
                          to query task status
                        examples:
                          - veo_task_abcdef123456
                      resultUrls:
                        type: array
                        items:
                          type: string
                        description: Generated 4K video URLs
                        examples:
                          - - >-
                              https://file.aiquickdraw.com/v/example_task_1234567890.mp4
                      imageUrls:
                        type: array
                        items:
                          type: string
                        description: Related thumbnail or preview image URLs
                        examples:
                          - - >-
                              https://file.aiquickdraw.com/v/example_task_1234567890.jpg
                    x-apidog-orders:
                      - taskId
                      - resultUrls
                      - imageUrls
                    x-apidog-ignore-properties: []
                x-apidog-orders:
                  - code
                  - msg
                  - data
                x-apidog-ignore-properties: []
              example:
                code: 200
                msg: success
                data:
                  taskId: veo_task_abcdef123456
                  resultUrls: null
                  imageUrls: null
          headers: {}
          x-apidog-name: ''
        '500':
          description: request failed
          content:
            application/json:
              schema:
                type: object
                properties:
                  code:
                    type: integer
                    description: >-
                      Response status code


                      - **200**: Success - Request has been processed
                      successfully

                      - **401**: Unauthorized - Authentication credentials are
                      missing or invalid

                      - **402**: Insufficient Credits - Account does not have
                      enough credits to perform the operation

                      - **404**: Not Found - The requested resource or endpoint
                      does not exist

                      - **408**: Upstream is currently experiencing service
                      issues. No result has been returned for over 10 minutes.

                      - **422**: Validation Error - The request parameters
                      failed validation checks

                      - **429**: Rate Limited - Request limit has been exceeded
                      for this resource

                      - **455**: Service Unavailable - System is currently
                      undergoing maintenance

                      - **500**: Server Error - An unexpected error occurred
                      while processing the request

                      - **501**: Generation Failed - Content generation task
                      failed

                      - **505**: Feature Disabled - The requested feature is
                      currently disabled
                  msg:
                    type: string
                    description: Response message, error description when failed
                  data:
                    type: object
                    properties: {}
                    x-apidog-orders: []
                    x-apidog-ignore-properties: []
                x-apidog-orders:
                  - code
                  - msg
                  - data
                required:
                  - code
                  - msg
                  - data
                x-apidog-ignore-properties: []
              example:
                code: 500
                msg: >-
                  Server Error - An unexpected error occurred while processing
                  the request
                data: null
          headers: {}
          x-apidog-name: 'Error '
      security:
        - BearerAuth: []
          x-apidog:
            schemeGroups:
              - id: kn8M4YUlc5i0A0179ezwx
                schemeIds:
                  - BearerAuth
            required: true
            use:
              id: kn8M4YUlc5i0A0179ezwx
            scopes:
              kn8M4YUlc5i0A0179ezwx:
                BearerAuth: []
      callbacks:
        on4KVideoGenerated:
          '{$request.body#/callBackUrl}':
            post:
              summary: 4K Video Generation Callback
              description: >-
                When the 4K video generation task completes, the system will
                send a POST request to your configured callback URL
              requestBody:
                required: true
                content:
                  application/json:
                    schema:
                      type: object
                      properties:
                        code:
                          type: integer
                          description: >-
                            Status code


                            - **200**: Success - 4K video generation task
                            successful
                          enum:
                            - 200
                            - 400
                            - 500
                        msg:
                          type: string
                          description: Status message
                          example: 4K Video generated successfully.
                        data:
                          type: object
                          properties:
                            task_id:
                              type: string
                              description: Task ID
                              example: bf3e7adb-fb6c-4257-bbcd-470787386fb0
                            result_urls:
                              type: array
                              items:
                                type: string
                              description: Generated 4K video URLs
                              example:
                                - >-
                                  https://file.aiquickdraw.com/p/d1301f0aa3f647c1ab7bb1f60ef006c0_1750236843.mp4
                            media_ids:
                              type: array
                              items:
                                type: string
                              description: Media IDs
                              example:
                                - >-
                                  CAUaJDQ5NGYwY2NhLTE1NTUtNDIzNS1iNjJiLWE0OWE4NzMxNjMzOCIDQ0FFKi4xMDJlOTA5MS01NGJlLTQzN2EtODhkMC01NWNkNGUxNTllNTNfdXBzYW1wbGVk
                            image_urls:
                              type: array
                              items:
                                type: string
                              description: Related image URLs
                              example:
                                - >-
                                  https://tempfile.aiquickdraw.com/p/d1301f0aa3f647c1ab7bb1f60ef006c0_1750236843.jpg
              responses:
                '200':
                  description: Callback received successfully
      x-apidog-folder: docs/en/Market/Veo3.1 API
      x-apidog-status: released
      x-run-in-apidog: https://app.apidog.com/web/project/1184766/apis/api-28506314-run
components:
  schemas: {}
  securitySchemes:
    BearerAuth:
      type: bearer
      scheme: bearer
      bearerFormat: API Key
      description: |-
        所有 API 都需要通过 Bearer Token 进行身份验证。

        获取 API Key：
        1. 访问 [API Key 管理页面](https://kie.ai/api-key) 获取您的 API Key

        使用方法：
        在请求头中添加：
        Authorization: Bearer YOUR_API_KEY

        注意事项：
        - 请妥善保管您的 API Key，切勿泄露给他人
        - 若怀疑 API Key 泄露，请立即在管理页面重置
servers:
  - url: https://api.kie.ai
    description: 正式环境
security:
  - BearerAuth: []
    x-apidog:
      schemeGroups:
        - id: kn8M4YUlc5i0A0179ezwx
          schemeIds:
            - BearerAuth
      required: true
      use:
        id: kn8M4YUlc5i0A0179ezwx
      scopes:
        kn8M4YUlc5i0A0179ezwx:
          BearerAuth: []

```
# Get 1080P Video

## OpenAPI Specification

```yaml
openapi: 3.0.1
info:
  title: ''
  description: ''
  version: 1.0.0
paths:
  /api/v1/veo/get-1080p-video:
    get:
      summary: Get 1080P Video
      deprecated: false
      description: >
        ::: info[]
          Get the high-definition 1080P version of a Veo 3.1 video generation task.
        :::


        ::: note[]
          Legacy note: If your task was generated via a deprecated fallback path, 1080P may already be the default output and this endpoint may not apply.
        :::


        ### Usage Instructions


        * 1080P generation requires extra processing time — typically **~1–3
        minutes** depending on load.

        * If the 1080P video is not ready yet, the endpoint may return a non-200
        code. In this case, wait a bit and retry (recommended interval:
        **20–30s**) until the result is available.

        * Make sure the **original generation task is successful** before
        requesting 1080P.
      operationId: get-veo3-1-1080p-video
      tags:
        - docs/en/Market/Veo3.1 API
      parameters:
        - name: taskId
          in: query
          description: Task ID
          required: true
          example: veo_task_abcdef123456
          schema:
            type: string
        - name: index
          in: query
          description: video index
          required: false
          example: 0
          schema:
            type: integer
      responses:
        '200':
          description: Request successful
          content:
            application/json:
              schema:
                type: object
                properties:
                  code:
                    type: integer
                    enum:
                      - 200
                      - 401
                      - 404
                      - 422
                      - 429
                      - 451
                      - 455
                      - 500
                    description: >-
                      Response status code


                      - **200**: Success - Request has been processed
                      successfully

                      - **401**: Unauthorized - Authentication credentials are
                      missing or invalid

                      - **404**: Not Found - The requested resource or endpoint
                      does not exist

                      - **422**: Validation Error - The request parameters
                      failed validation checks.

                      record is null.

                      Temporarily supports records within 14 days.

                      record result data is blank.

                      record status is not success.

                      record result data not exist.

                      record result data is empty.

                      - **429**: Rate Limited - Request limit has been exceeded
                      for this resource

                      - **451**: Failed to fetch the image. Kindly verify any
                      access limits set by you or your service provider.

                      - **455**: Service Unavailable - System is currently
                      undergoing maintenance

                      - **500**: Server Error - An unexpected error occurred
                      while processing the request
                  msg:
                    type: string
                    description: Error message when code != 200
                    examples:
                      - success
                  data:
                    type: object
                    properties:
                      resultUrl:
                        type: string
                        description: 1080P high-definition video download URL
                        examples:
                          - >-
                            https://tempfile.aiquickdraw.com/p/42f4f8facbb040c0ade87c27cb2d5e58_1749711595.mp4
                    x-apidog-orders:
                      - resultUrl
                    x-apidog-ignore-properties: []
                x-apidog-orders:
                  - code
                  - msg
                  - data
                x-apidog-ignore-properties: []
              example:
                code: 200
                msg: success
                data:
                  resultUrl: >-
                    https://tempfile.aiquickdraw.com/p/42f4f8facbb040c0ade87c27cb2d5e58_1749711595.mp4
          headers: {}
          x-apidog-name: ''
        '500':
          description: request failed
          content:
            application/json:
              schema:
                type: object
                properties:
                  code:
                    type: integer
                    description: >-
                      Response status code


                      - **200**: Success - Request has been processed
                      successfully

                      - **401**: Unauthorized - Authentication credentials are
                      missing or invalid

                      - **402**: Insufficient Credits - Account does not have
                      enough credits to perform the operation

                      - **404**: Not Found - The requested resource or endpoint
                      does not exist

                      - **408**: Upstream is currently experiencing service
                      issues. No result has been returned for over 10 minutes.

                      - **422**: Validation Error - The request parameters
                      failed validation checks

                      - **429**: Rate Limited - Request limit has been exceeded
                      for this resource

                      - **455**: Service Unavailable - System is currently
                      undergoing maintenance

                      - **500**: Server Error - An unexpected error occurred
                      while processing the request

                      - **501**: Generation Failed - Content generation task
                      failed

                      - **505**: Feature Disabled - The requested feature is
                      currently disabled
                  msg:
                    type: string
                    description: Response message, error description when failed
                  data:
                    type: object
                    properties: {}
                    x-apidog-orders: []
                    x-apidog-ignore-properties: []
                x-apidog-orders:
                  - code
                  - msg
                  - data
                required:
                  - code
                  - msg
                  - data
                x-apidog-ignore-properties: []
              example:
                code: 500
                msg: >-
                  Server Error - An unexpected error occurred while processing
                  the request
                data: null
          headers: {}
          x-apidog-name: 'Error '
      security:
        - BearerAuth: []
          x-apidog:
            schemeGroups:
              - id: kn8M4YUlc5i0A0179ezwx
                schemeIds:
                  - BearerAuth
            required: true
            use:
              id: kn8M4YUlc5i0A0179ezwx
            scopes:
              kn8M4YUlc5i0A0179ezwx:
                BearerAuth: []
      x-apidog-folder: docs/en/Market/Veo3.1 API
      x-apidog-status: released
      x-run-in-apidog: https://app.apidog.com/web/project/1184766/apis/api-28506313-run
components:
  schemas: {}
  securitySchemes:
    BearerAuth:
      type: bearer
      scheme: bearer
      bearerFormat: API Key
      description: |-
        所有 API 都需要通过 Bearer Token 进行身份验证。

        获取 API Key：
        1. 访问 [API Key 管理页面](https://kie.ai/api-key) 获取您的 API Key

        使用方法：
        在请求头中添加：
        Authorization: Bearer YOUR_API_KEY

        注意事项：
        - 请妥善保管您的 API Key，切勿泄露给他人
        - 若怀疑 API Key 泄露，请立即在管理页面重置
servers:
  - url: https://api.kie.ai
    description: 正式环境
security:
  - BearerAuth: []
    x-apidog:
      schemeGroups:
        - id: kn8M4YUlc5i0A0179ezwx
          schemeIds:
            - BearerAuth
      required: true
      use:
        id: kn8M4YUlc5i0A0179ezwx
      scopes:
        kn8M4YUlc5i0A0179ezwx:
          BearerAuth: []

```
# Extend Veo3.1 Video

## OpenAPI Specification

```yaml
openapi: 3.0.1
info:
  title: ''
  description: ''
  version: 1.0.0
paths:
  /api/v1/veo/extend:
    post:
      summary: Extend Veo3.1 Video
      deprecated: false
      description: >
        ::: info[]
          Extend an existing Veo 3.1 video by generating new content based on the original video and a text prompt. This feature allows you to extend video duration or add new content based on your existing video clips.
        :::


        Our **Veo 3.1 Video Extension API** is more than simple video splicing.
        It layers intelligent extension algorithms on top of the official
        models, giving you greater flexibility and markedly higher success rates
        — **25% of the official Google pricing** (see [pricing
        details](https://kie.ai/pricing) for full details).


        | Capability              | Details |

        | :---------------------- | :------ |

        | **Smart Extension**     | Generate new video segments based on
        existing videos and text prompts |

        | **Seamless Connection** | Extended videos naturally connect with the
        original video |

        | **Flexible Control**    | Precisely control the style and actions of
        extended content through prompts |

        | **High-Quality Output** | Maintain the same quality and style as the
        original video |

        | **Audio Track**         | Extended videos default to background audio,
        consistent with the original video |


        ### Why our Veo 3.1 Video Extension is different


        1. **Smart Content Understanding** – Deeply understands the content and
        style of the original video to ensure coherence of extended content.

        2. **Natural Transition** – Extended video segments seamlessly connect
        with the original video without visible splicing marks.

        3. **Flexible Control** – Precisely control the actions, scenes, and
        styles of extended content through detailed prompts.

        4. **Significant Cost Savings** – Our rates are 25% of Google's direct
        API pricing.


        ***


        ### Video Extension Workflow


        The video extension feature is based on your existing Veo3.1 generated
        videos and works through the following steps:


        1. **Provide Original Video**: Use the `taskId` from the original video
        generation task

        2. **Describe Extension Content**: Use `prompt` to detail how you want
        the video to be extended

        3. **Smart Analysis**: The system analyzes the content, style, and
        actions of the original video

        4. **Generate Extension**: Generate new video segments based on analysis
        results and your prompts

        5. **Seamless Connection**: Naturally connect the extended video with
        the original video


        ### Extension Features


        ::: info[Through the video extension feature, you can:]

        - Extend video duration and add more content

        - Change video direction and add new actions or scenes

        - Add new elements while maintaining the original style

        - Create richer video stories

        :::


        **Extension Features:**


        - **Smart Analysis**: Deeply understand the content and style of the
        original video

        - **Natural Connection**: Extended content seamlessly connects with the
        original video

        - **Flexible Control**: Precisely control extended content through
        prompts

        - **Quality Assurance**: Maintain the same quality and style as the
        original video


        ::: warning[**Important Notes**]

        - Can only extend videos generated through the Veo3.1 API

        - Extended content must also comply with platform content policies

        - Recommend using English prompts for best results

        - Video extension consumes credits, see [pricing
        Details](https://kie.ai/pricing) for specific pricing

        :::


        ### Best Practices


        ::: tip[Prompt Writing Suggestions]

        1. **Detailed Action Description**: Clearly describe how you want the
        video to be extended, e.g., "the dog continues running through the park,
        jumping over obstacles"

        2. **Maintain Style Consistency**: Ensure the style of extended content
        matches the original video

        3. **Natural Transition**: Described actions should naturally connect
        with the end of the original video

        4. **Use English**: Recommend using English prompts for best results

        5. **Avoid Conflicts**: Ensure extended content doesn't create logical
        conflicts with the original video

        :::


        ::: tip[Technical Recommendations]

        1. **Use Callbacks**: Strongly recommend using callback mechanisms to
        get results in production environments

        2. **Download Promptly**: Download video files promptly after
        generation, URLs have time limits

        3. **Error Handling**: Implement appropriate error handling and retry
        mechanisms

        4. **Credit Management**: Monitor credit usage to ensure sufficient
        balance

        5. **Seed Control**: Use the seeds parameter to control the randomness
        of generated content

        :::


        ## Important Notes


        ::: warning[Important Limitations]

        - **Original Video Requirements**: Can only extend videos generated
        through the Veo3.1 API

        - **Content Policy**: Extended content must also comply with platform
        content policies

        - **Credit Consumption**: Video extension consumes credits, see [pricing
        Details](https://kie.ai/pricing) for specific pricing

        - **Processing Time**: Video extension may take several minutes to over
        ten minutes to process

        - **URL Validity**: Generated video URLs have time limits, please
        download and save promptly

        :::


        ::: note[Extended Video Features]

        - **Seamless Connection**: Extended videos will naturally connect with
        the original video

        - **Quality Maintenance**: Extended videos maintain the same quality as
        the original video

        - **Style Consistency**: Extended content will maintain the visual style
        of the original video

        - **Flexible Control**: Prompts can precisely control the content and
        direction of extension

        :::


        ## Troubleshooting


        <AccordionGroup>

        <Accordion title="Common Error Handling">

        - **404 Error**: Check if task_id and media_id are correct

        - **400 Error**: Check if the prompt complies with content policies

        - **402 Error**: Confirm the account has sufficient credits

        - **500 Error**: Temporary server issue, please try again later

        </Accordion>


        <Accordion title="Extension Quality Issues">

        - **Unnatural Connection**: Try more detailed prompt descriptions

        - **Style Inconsistency**: Ensure the prompt includes style descriptions

        - **Disconnected Actions**: Check if action descriptions in the prompt
        are reasonable

        - **Content Deviation**: Adjust prompts to more accurately describe
        desired extension content

        </Accordion>


        <Accordion title="Technical Issues">

        - **Callback Receipt Failure**: Check if the callback URL is accessible

        - **Video Download Failure**: Confirm URL validity and network
        connection

        - **Abnormal Task Status**: Use the details query interface to check
        task status

        - **Insufficient Credits**: Recharge credits promptly to continue using
        the service

        </Accordion>

        </AccordionGroup>
      operationId: extend-veo3-1-video
      tags:
        - docs/en/Market/Veo3.1 API
      parameters: []
      requestBody:
        content:
          application/json:
            schema:
              type: object
              properties:
                taskId:
                  type: string
                  description: >-
                    Task ID of the original video generation. Must be a valid
                    taskId returned from the video generation interface. Note:
                    Videos generated after 1080P generation cannot be extended.
                  examples:
                    - veo_task_abcdef123456
                prompt:
                  type: string
                  description: >-
                    Text prompt describing the extended video content. Should
                    detail how you want the video to be extended, including
                    actions, scene changes, style, etc.
                  examples:
                    - >-
                      The dog continues running through the park, jumping over
                      obstacles and playing with other dogs
                seeds:
                  type: integer
                  description: >-
                    Random seed parameter for controlling the randomness of
                    generated content. Range: 10000-99999. Same seeds will
                    generate similar video content, different seeds will
                    generate different video content. If not specified, the
                    system will automatically assign random seeds.
                  minimum: 10000
                  maximum: 99999
                  examples:
                    - 12345
                model:
                  type: string
                  description: >-
                    Model type for video extension (optional). Defaults to
                    `fast` if not specified.


                    - **fast**: Fast generation mode

                    - **quality**: High quality generation mode

                    - **lite**: Most cost-effective generation mode
                  enum:
                    - fast
                    - quality
                    - lite
                  default: fast
                  examples:
                    - fast
                watermark:
                  type: string
                  description: >-
                    Watermark text (optional). If provided, a watermark will be
                    added to the generated video.
                  examples:
                    - MyBrand
                callBackUrl:
                  type: string
                  description: >-
                    Callback URL when the task is completed (optional). Strongly
                    recommended for production environments.


                    - The system will send a POST request to this URL when video
                    extension is completed, containing task status and results

                    - The callback contains generated video URLs, task
                    information, etc.

                    - Your callback endpoint should accept POST requests with
                    JSON payloads containing video results

                    - For detailed callback format and implementation guide, see
                    [Video Generation
                    Callbacks](https://docs.kie.ai/veo3-api/generate-veo-3-video-callbacks)

                    - Alternatively, you can use [the get video details
                    interface](https://docs.kie.ai/veo3-api/get-veo-3-video-details)
                    to poll task status

                    - To ensure callback security, see [Webhook Verification
                    Guide](/common-api/webhook-verification) for signature
                    verification implementation
                  examples:
                    - https://your-callback-url.com/veo-extend-callback
              required:
                - taskId
                - prompt
              x-apidog-orders:
                - taskId
                - prompt
                - seeds
                - model
                - watermark
                - callBackUrl
              examples:
                - taskId: veo_task_abcdef123456
                  prompt: >-
                    The dog continues running through the park, jumping over
                    obstacles and playing with other dogs
                  seeds: 12345
                  model: fast
                  watermark: MyBrand
                  callBackUrl: https://your-callback-url.com/veo-extend-callback
              x-apidog-ignore-properties: []
            example:
              taskId: veo_task_abcdef123456
              prompt: >-
                The dog continues running through the park, jumping over
                obstacles and playing with other dogs
              seeds: 12345
              watermark: MyBrand
              callBackUrl: https://your-callback-url.com/veo-extend-callback
              model: fast
      responses:
        '200':
          description: Request successful
          content:
            application/json:
              schema:
                type: object
                properties:
                  code:
                    type: integer
                    enum:
                      - 200
                      - 400
                      - 401
                      - 402
                      - 404
                      - 422
                      - 429
                      - 455
                      - 500
                      - 501
                      - 505
                    description: >-
                      Response status code


                      - **200**: Success - Extension task created

                      - **400**: Client error - Prompt violates content policy
                      or other input errors

                      - **401**: Unauthorized - Authentication credentials
                      missing or invalid

                      - **402**: Insufficient credits - Account does not have
                      enough credits to perform the operation

                      - **404**: Not found - Original video or task does not
                      exist

                      - **422**: Validation error - Request parameter validation
                      failed

                      - **429**: Rate limit - Exceeded the request limit for
                      this resource

                      - **455**: Service unavailable - System is under
                      maintenance

                      - **500**: Server error - Unexpected error occurred while
                      processing the request

                      - **501**: Extension failed - Video extension task failed

                      - **505**: Feature disabled - The requested feature is
                      currently disabled
                  msg:
                    type: string
                    description: Response message
                    examples:
                      - success
                  data:
                    type: object
                    properties:
                      taskId:
                        type: string
                        description: >-
                          Task ID that can be used to query task status via the
                          get video details interface
                        examples:
                          - veo_extend_task_xyz789
                    x-apidog-orders:
                      - taskId
                    x-apidog-ignore-properties: []
                x-apidog-orders:
                  - code
                  - msg
                  - data
                examples:
                  - code: 200
                    msg: success
                    data:
                      taskId: veo_extend_task_xyz789
                x-apidog-ignore-properties: []
          headers: {}
          x-apidog-name: ''
        '500':
          description: request failed
          content:
            application/json:
              schema:
                type: object
                properties:
                  code:
                    type: integer
                    description: >-
                      Response status code


                      - **200**: Success - Request has been processed
                      successfully

                      - **401**: Unauthorized - Authentication credentials are
                      missing or invalid

                      - **402**: Insufficient Credits - Account does not have
                      enough credits to perform the operation

                      - **404**: Not Found - The requested resource or endpoint
                      does not exist

                      - **408**: Upstream is currently experiencing service
                      issues. No result has been returned for over 10 minutes.

                      - **422**: Validation Error - The request parameters
                      failed validation checks

                      - **429**: Rate Limited - Request limit has been exceeded
                      for this resource

                      - **455**: Service Unavailable - System is currently
                      undergoing maintenance

                      - **500**: Server Error - An unexpected error occurred
                      while processing the request

                      - **501**: Generation Failed - Content generation task
                      failed

                      - **505**: Feature Disabled - The requested feature is
                      currently disabled
                  msg:
                    type: string
                    description: Response message, error description when failed
                  data:
                    type: object
                    properties: {}
                    x-apidog-orders: []
                    x-apidog-ignore-properties: []
                x-apidog-orders:
                  - code
                  - msg
                  - data
                required:
                  - code
                  - msg
                  - data
                x-apidog-ignore-properties: []
              example:
                code: 500
                msg: >-
                  Server Error - An unexpected error occurred while processing
                  the request
                data: null
          headers: {}
          x-apidog-name: 'Error '
      security:
        - BearerAuth: []
          x-apidog:
            schemeGroups:
              - id: kn8M4YUlc5i0A0179ezwx
                schemeIds:
                  - BearerAuth
            required: true
            use:
              id: kn8M4YUlc5i0A0179ezwx
            scopes:
              kn8M4YUlc5i0A0179ezwx:
                BearerAuth: []
      callbacks:
        onVideoExtended:
          '{$request.body#/callBackUrl}':
            post:
              summary: Video Extension Callback
              description: >-
                When the video extension task is completed, the system will send
                the result to your provided callback URL via POST request
              requestBody:
                required: true
                content:
                  application/json:
                    schema:
                      type: object
                      properties:
                        code:
                          type: integer
                          description: >-
                            Status code


                            - **200**: Success - Video extension task successful

                            - **400**: Your prompt was flagged by the website as
                            violating content policies.

                            English prompts only.

                            Unable to retrieve image. Please verify any access
                            restrictions set by you or your service provider.

                            Public error: Unsafe image upload.

                            - **500**: Internal error, please try again later.

                            Internal error - Timeout

                            - **501**: Failed - Video extension task failed
                          enum:
                            - 200
                            - 400
                            - 500
                            - 501
                        msg:
                          type: string
                          description: Status message
                          example: Veo3.1 video extension successful.
                        data:
                          type: object
                          properties:
                            taskId:
                              type: string
                              description: Task ID
                              example: veo_extend_task_xyz789
                            info:
                              type: object
                              properties:
                                resultUrls:
                                  type: string
                                  description: Extended video URLs
                                  example: '[http://example.com/extended_video1.mp4]'
                                originUrls:
                                  type: string
                                  description: >-
                                    Original video URLs. Only available when
                                    aspect_ratio is not 16:9
                                  example: '[http://example.com/original_video1.mp4]'
                                resolution:
                                  type: string
                                  description: Video resolution information
                                  example: 1080p
                            fallbackFlag:
                              type: boolean
                              description: >-
                                Whether generated through fallback model. true
                                means using backup model generation, false means
                                using main model generation
                              example: false
                              deprecated: true
              responses:
                '200':
                  description: Callback received successfully
      x-apidog-folder: docs/en/Market/Veo3.1 API
      x-apidog-status: released
      x-run-in-apidog: https://app.apidog.com/web/project/1184766/apis/api-28506315-run
components:
  schemas: {}
  securitySchemes:
    BearerAuth:
      type: bearer
      scheme: bearer
      bearerFormat: API Key
      description: |-
        所有 API 都需要通过 Bearer Token 进行身份验证。

        获取 API Key：
        1. 访问 [API Key 管理页面](https://kie.ai/api-key) 获取您的 API Key

        使用方法：
        在请求头中添加：
        Authorization: Bearer YOUR_API_KEY

        注意事项：
        - 请妥善保管您的 API Key，切勿泄露给他人
        - 若怀疑 API Key 泄露，请立即在管理页面重置
servers:
  - url: https://api.kie.ai
    description: 正式环境
security:
  - BearerAuth: []
    x-apidog:
      schemeGroups:
        - id: kn8M4YUlc5i0A0179ezwx
          schemeIds:
            - BearerAuth
      required: true
      use:
        id: kn8M4YUlc5i0A0179ezwx
      scopes:
        kn8M4YUlc5i0A0179ezwx:
          BearerAuth: []

```
# Generate Veo3.1 Video

## OpenAPI Specification

```yaml
openapi: 3.0.1
info:
  title: ''
  description: ''
  version: 1.0.0
paths:
  /api/v1/veo/generate:
    post:
      summary: Generate Veo3.1 Video
      deprecated: false
      description: >-
        ### Veo 3.1 Generation API


        Our **Veo 3.1 Generation API** is more than a direct wrapper around
        Google's baseline. It layers extensive optimisation and reliability
        tooling on top of the official models, giving you greater flexibility
        and markedly higher success rates — **25% of the official Google
        pricing** (see [kie.ai/pricing](https://kie.ai/pricing) for full
        details).


        | Capability | Details |

        | :------------------- | :------ |

        | **Models** | • **Veo 3.1 Quality** — flagship model, highest fidelity•
        **Veo 3.1 Fast** — cost-efficient variant that still delivers strong
        visual results• **Veo 3.1 Lite** — most cost-effective model for
        high-volume generation |

        | **Tasks** | • **Text → Video**• **Image → Video** (single reference
        frame or first and last frames)• **Material → Video** (based on material
        images) |

        | **Generation Modes** | • **TEXT\_2\_VIDEO** — Text-to-video: using
        text prompts only• **FIRST\_AND\_LAST\_FRAMES\_2\_VIDEO** — First and
        last frames to video: generate transition videos using one or two
        images• **REFERENCE\_2\_VIDEO** — Material-to-video: based on material
        images (**Fast model only**, supports **16:9 & 9:16**) |

        | **Aspect Ratios** | Supports both native **16:9** and **9:16**
        outputs. **Auto** mode lets the system decide aspect ratio based on
        input materials and internal strategy (for production control, we
        recommend explicitly setting `aspect_ratio`). |

        | **Output Quality** | Both **16:9** and **9:16** support **1080P** and
        **4K** outputs. **4K requires extra credits** (approximately **2× the
        credits of generating a Fast mode video**) and is requested via a
        separate 4K endpoint. |

        | **Audio Track** | All videos ship with background audio by default. In
        rare cases, upstream may suppress audio when the scene is deemed
        sensitive (e.g. minors). |


        ### Why our Veo 3.1 API is different


        1. **True vertical video** – Native Veo 3.1 supports **9:16** output,
        delivering authentic vertical videos without the need for re-framing or
        manual editing.

        2. **Global language reach** – Our flow supports multilingual prompts by
        default (no extra configuration required).

        3. **Significant cost savings** – Our rates are 25% of Google's direct
        API pricing.
      operationId: generate-veo3-1-video
      tags:
        - docs/en/Market/Veo3.1 API
      parameters: []
      requestBody:
        content:
          application/json:
            schema:
              type: object
              properties:
                prompt:
                  type: string
                  description: >-
                    Text prompt describing the desired video content. Required
                    for all generation modes.


                    - Should be detailed and specific in describing video
                    content

                    - Can include actions, scenes, style and other information

                    - For image-to-video, describe how you want the image to
                    come alive
                  examples:
                    - A dog playing in a park
                imageUrls:
                  type: array
                  items:
                    type: string
                  description: >-
                    Image URL list (used in image-to-video mode). Supports 1 or
                    2 images:


                    - **1 image**: The generated video will unfold around this
                    image, with the image content presented dynamically

                    - **2 images**: The first image serves as the video's first
                    frame, and the second image serves as the video's last
                    frame, with the video transitioning between them

                    - Must be valid image URLs

                    - Images must be accessible to the API server.
                  examples:
                    - - http://example.com/image1.jpg
                      - http://example.com/image2.jpg
                model:
                  type: string
                  description: >-
                    Select the model type to use.


                    - veo3: Veo 3.1 Quality, supports both text-to-video and
                    image-to-video generation

                    - veo3_fast: Veo3.1 Fast generation model, supports both
                    text-to-video and image-to-video generation
                  enum:
                    - veo3
                    - veo3_fast
                    - veo3_lite
                  default: veo3_fast
                  examples:
                    - veo3_fast
                  x-apidog-enum:
                    - value: veo3
                      name: ''
                      description: ''
                    - value: veo3_fast
                      name: ''
                      description: ''
                    - value: veo3_lite
                      name: ''
                      description: ''
                generationType:
                  type: string
                  description: >-
                    Video generation mode (optional). Specifies different video
                    generation approaches:


                    - **TEXT_2_VIDEO**: Text-to-video - Generate videos using
                    only text prompts

                    - **FIRST_AND_LAST_FRAMES_2_VIDEO**: First and last frames
                    to video - Flexible image-to-video generation mode
                      - 1 image: Generate video based on the provided image
                      - 2 images: First image as first frame, second image as last frame, generating transition video
                    - **REFERENCE_2_VIDEO**: Reference-to-video - Generate
                    videos based on reference images, requires 1-3 images in
                    imageUrls (minimum 1, maximum 3)


                    **Important Notes**:

                    - REFERENCE_2_VIDEO mode currently only supports veo3_fast
                    model

                    - If not specified, the system will automatically determine
                    the generation mode based on whether imageUrls are provided
                  enum:
                    - TEXT_2_VIDEO
                    - FIRST_AND_LAST_FRAMES_2_VIDEO
                    - REFERENCE_2_VIDEO
                  examples:
                    - TEXT_2_VIDEO
                aspect_ratio:
                  type: string
                  description: >-
                    Video aspect ratio. Specifies the dimension ratio of the
                    generated video. Available options:


                    - 16:9: Landscape video format. 

                    - 9:16: Portrait video format, suitable for mobile short
                    videos

                    - Auto: In auto mode, the video will be automatically
                    center-cropped based on whether your uploaded image is
                    closer to 16:9 or 9:16.


                    Default value is 16:9.
                  enum:
                    - '16:9'
                    - '9:16'
                    - Auto
                  default: '16:9'
                  examples:
                    - '16:9'
                callBackUrl:
                  type: string
                  description: >-
                    Completion callback URL for receiving video generation
                    status updates.


                    - Optional but recommended for production use

                    - System will POST task completion status to this URL when
                    the video generation is completed

                    - Callback will include task results, video URLs, and status
                    information

                    - Your callback endpoint should accept POST requests with
                    JSON payload

                    - For detailed callback format and implementation guide, see
                    [Callback
                    Documentation](https://docs.kie.ai/veo3-api/generate-veo-3-video-callbacks)

                    - Alternatively, use the Get Video Details endpoint to poll
                    task status

                    - To ensure callback security, see [Webhook Verification
                    Guide](/common-api/webhook-verification) for signature
                    verification implementation
                  examples:
                    - http://your-callback-url.com/complete
                enableFallback:
                  type: boolean
                  description: >-
                    Deprecated Enable fallback functionality. When set to true,
                    if the official Veo3.1 video generation service is
                    unavailable or encounters exceptions, the system will
                    automatically switch to a backup model for video generation
                    to ensure task continuity and reliability. Default value is
                    false.


                    - When fallback is enabled, backup model will be used for
                    the following errors:
                      - public error minor upload
                      - Your prompt was flagged by Website as violating content policies
                      - public error prominent people upload
                    - Fallback mode requires 16:9 aspect ratio and uses 1080p
                    resolution by default

                    - **Note**: Videos generated through fallback mode cannot be
                    accessed via the Get 1080P Video endpoint

                    - **Credit Consumption**: Successful fallback has different
                    credit consumption, please see https://kie.ai/pricing for
                    pricing details


                    **Note: This parameter is deprecated. Please remove this
                    parameter from your requests. The system has automatically
                    optimized the content review mechanism without requiring
                    manual fallback configuration.**
                  default: false
                  deprecated: true
                  examples:
                    - false
                enableTranslation:
                  type: boolean
                  description: >-
                    Enable prompt translation to English. When set to true, the
                    system will automatically translate prompts to English
                    before video generation for better generation results.
                    Default value is true.


                    - true: Enable translation, prompts will be automatically
                    translated to English

                    - false: Disable translation, use original prompts directly
                    for generation
                  default: true
                  examples:
                    - true
                watermark:
                  type: string
                  description: >-
                    Watermark text.


                    - Optional parameter

                    - If provided, a watermark will be added to the generated
                    video
                  examples:
                    - MyBrand
                resolution:
                  type: string
                  enum:
                    - 720p
                    - 1080p
                    - 4k
                  x-apidog-enum:
                    - value: 720p
                      name: ''
                      description: ''
                    - value: 1080p
                      name: ''
                      description: ''
                    - value: 4k
                      name: ''
                      description: ''
                  default: 720p
                  description: >-
                    Controls the pixel dimensions of the generated image. Higher
                    resolution results in greater clarity and detail, while
                    lower resolution allows for faster generation.
              required:
                - prompt
              x-apidog-orders:
                - prompt
                - imageUrls
                - model
                - generationType
                - aspect_ratio
                - callBackUrl
                - enableFallback
                - enableTranslation
                - watermark
                - resolution
              examples:
                - prompt: A dog playing in a park
                  imageUrls:
                    - http://example.com/image1.jpg
                    - http://example.com/image2.jpg
                  model: veo3_fast
                  watermark: MyBrand
                  callBackUrl: http://your-callback-url.com/complete
                  aspect_ratio: '16:9'
                  seeds: 12345
                  enableFallback: false
                  enableTranslation: true
                  generationType: REFERENCE_2_VIDEO
              x-apidog-ignore-properties: []
            example:
              prompt: A dog playing in a park
              imageUrls:
                - http://example.com/image1.jpg
                - http://example.com/image2.jpg
              model: veo3_fast
              watermark: MyBrand
              callBackUrl: http://your-callback-url.com/complete
              aspect_ratio: '16:9'
              enableFallback: false
              enableTranslation: true
              generationType: REFERENCE_2_VIDEO
      responses:
        '200':
          description: Request successful
          content:
            application/json:
              schema:
                type: object
                properties:
                  code:
                    type: integer
                    enum:
                      - 200
                      - 400
                      - 401
                      - 402
                      - 404
                      - 422
                      - 429
                      - 455
                      - 500
                      - 501
                      - 505
                    description: >-
                      Response status code


                      - **200**: Success - Request has been processed
                      successfully

                      - **400**: 1080P is processing. It should be ready in 1-2
                      minutes. Please check back shortly.

                      - **401**: Unauthorized - Authentication credentials are
                      missing or invalid

                      - **402**: Insufficient Credits - Account does not have
                      enough credits to perform the operation

                      - **404**: Not Found - The requested resource or endpoint
                      does not exist

                      - **422**: Validation Error - Request parameters failed
                      validation. When fallback is not enabled and generation
                      fails, error message format: Your request was rejected by
                      Flow(original error message). You may consider using our
                      other fallback channels, which are likely to succeed.
                      Please refer to the documentation.

                      - **429**: Rate Limited - Request limit has been exceeded
                      for this resource

                      - **455**: Service Unavailable - System is currently
                      undergoing maintenance

                      - **500**: Server Error - An unexpected error occurred
                      while processing the request

                      - **501**: Generation Failed - Video generation task
                      failed

                      - **505**: Feature Disabled - The requested feature is
                      currently disabled
                  msg:
                    type: string
                    description: Error message when code != 200
                    examples:
                      - success
                  data:
                    type: object
                    properties:
                      taskId:
                        type: string
                        description: >-
                          Task ID, can be used with Get Video Details endpoint
                          to query task status
                        examples:
                          - veo_task_abcdef123456
                    x-apidog-orders:
                      - taskId
                    x-apidog-ignore-properties: []
                x-apidog-orders:
                  - code
                  - msg
                  - data
                x-apidog-ignore-properties: []
              example:
                code: 200
                msg: success
                data:
                  taskId: veo_task_abcdef123456
          headers: {}
          x-apidog-name: success
        '500':
          description: request failed
          content:
            application/json:
              schema:
                type: object
                properties:
                  code:
                    type: integer
                    description: >-
                      Response status code


                      - **200**: Success - Request has been processed
                      successfully

                      - **401**: Unauthorized - Authentication credentials are
                      missing or invalid

                      - **402**: Insufficient Credits - Account does not have
                      enough credits to perform the operation

                      - **404**: Not Found - The requested resource or endpoint
                      does not exist

                      - **408**: Upstream is currently experiencing service
                      issues. No result has been returned for over 10 minutes.

                      - **422**: Validation Error - The request parameters
                      failed validation checks

                      - **429**: Rate Limited - Request limit has been exceeded
                      for this resource

                      - **455**: Service Unavailable - System is currently
                      undergoing maintenance

                      - **500**: Server Error - An unexpected error occurred
                      while processing the request

                      - **501**: Generation Failed - Content generation task
                      failed

                      - **505**: Feature Disabled - The requested feature is
                      currently disabled
                  msg:
                    type: string
                    description: Response message, error description when failed
                  data:
                    type: object
                    properties: {}
                    x-apidog-orders: []
                    x-apidog-ignore-properties: []
                x-apidog-orders:
                  - code
                  - msg
                  - data
                required:
                  - code
                  - msg
                  - data
                x-apidog-ignore-properties: []
              example:
                code: 500
                msg: >-
                  Server Error - An unexpected error occurred while processing
                  the request
                data: null
          headers: {}
          x-apidog-name: 'Error '
      security:
        - BearerAuth: []
          x-apidog:
            schemeGroups:
              - id: kn8M4YUlc5i0A0179ezwx
                schemeIds:
                  - BearerAuth
            required: true
            use:
              id: kn8M4YUlc5i0A0179ezwx
            scopes:
              kn8M4YUlc5i0A0179ezwx:
                BearerAuth: []
      callbacks:
        onVideoGenerated:
          '{$request.body#/callBackUrl}':
            post:
              summary: Video Generation Callback
              description: >-
                When the video generation task is completed, the system will
                send the result to your provided callback URL via POST request
              requestBody:
                required: true
                content:
                  application/json:
                    schema:
                      type: object
                      properties:
                        code:
                          type: integer
                          description: >-
                            Status code


                            - **200**: Success - Video generation task
                            successfully

                            - **400**: Your prompt was flagged by Website as
                            violating content policies.

                            Only English prompts are supported at this time.

                            Failed to fetch the image. Kindly verify any access
                            limits set by you or your service provider.

                            public error unsafe image upload.

                            - **422**: Fallback failed - When fallback is not
                            enabled and specific errors occur, returns error
                            message format: Your request was rejected by
                            Flow(original error message). You may consider using
                            our other fallback channels, which are likely to
                            succeed. Please refer to the documentation.

                            - **500**: Internal Error, Please try again later.

                            Internal Error - Timeout

                            - **501**: Failed - Video generation task failed
                          enum:
                            - 200
                            - 400
                            - 422
                            - 500
                            - 501
                        msg:
                          type: string
                          description: Status message
                          example: Veo3.1 video generated successfully.
                        data:
                          type: object
                          properties:
                            taskId:
                              type: string
                              description: Task ID
                              example: veo_task_abcdef123456
                            info:
                              type: object
                              properties:
                                resultUrls:
                                  type: string
                                  description: Generated video URLs
                                  example: '[http://example.com/video1.mp4]'
                                originUrls:
                                  type: string
                                  description: >-
                                    Original video URLs. Only has value when
                                    aspect_ratio is not 16:9
                                  example: '[http://example.com/original_video1.mp4]'
                                resolution:
                                  type: string
                                  description: Video resolution information
                                  example: 1080p
                            fallbackFlag:
                              type: boolean
                              description: >-
                                Whether generated using fallback model. True
                                means backup model was used, false means primary
                                model was used
                              example: false
                              deprecated: true
              responses:
                '200':
                  description: Callback received successfully
      x-apidog-folder: docs/en/Market/Veo3.1 API
      x-apidog-status: released
      x-run-in-apidog: https://app.apidog.com/web/project/1184766/apis/api-28506311-run
components:
  schemas: {}
  securitySchemes:
    BearerAuth:
      type: bearer
      scheme: bearer
      bearerFormat: API Key
      description: |-
        所有 API 都需要通过 Bearer Token 进行身份验证。

        获取 API Key：
        1. 访问 [API Key 管理页面](https://kie.ai/api-key) 获取您的 API Key

        使用方法：
        在请求头中添加：
        Authorization: Bearer YOUR_API_KEY

        注意事项：
        - 请妥善保管您的 API Key，切勿泄露给他人
        - 若怀疑 API Key 泄露，请立即在管理页面重置
servers:
  - url: https://api.kie.ai
    description: 正式环境
security:
  - BearerAuth: []
    x-apidog:
      schemeGroups:
        - id: kn8M4YUlc5i0A0179ezwx
          schemeIds:
            - BearerAuth
      required: true
      use:
        id: kn8M4YUlc5i0A0179ezwx
      scopes:
        kn8M4YUlc5i0A0179ezwx:
          BearerAuth: []

```
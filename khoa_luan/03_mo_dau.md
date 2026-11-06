**MỞ ĐẦU**

**1. Lý do chọn đề tài**

Trong kinh doanh bán lẻ, chăm sóc khách hàng, gọi tắt là CSKH, là khâu tốn nhiều nhân lực và ảnh hưởng trực tiếp đến trải nghiệm mua sắm. Phần lớn yêu cầu mà bộ phận này tiếp nhận mang tính lặp lại: khách hàng hỏi tình trạng đơn hàng, theo dõi vận chuyển, kiểm tra tồn kho, tìm hiểu chính sách đổi trả hoặc muốn hủy, trả một đơn đã đặt. Khách hàng ngày càng mong được phản hồi ngay vào bất kỳ thời điểm nào, trong khi đội ngũ CSKH của các doanh nghiệp vừa và nhỏ thường có hạn. Các chatbot truyền thống dựa trên luật hoặc phân loại ý định chỉ xử lý tốt những câu hỏi đã có kịch bản sẵn; chúng dễ gãy khi khách đặt câu hỏi tiếp nối hoặc diễn đạt khác đi, và tốn công bảo trì mỗi khi nghiệp vụ thay đổi.

Sự phát triển của mô hình ngôn ngữ lớn, gọi tắt là LLM, mở ra một hướng tiếp cận khác. Với khả năng gọi công cụ và suy luận xen kẽ hành động như ReAct [Yao 2023], LLM có thể đóng vai một tác tử: tự lập kế hoạch, tra cứu dữ liệu thật thông qua các công cụ rồi tổng hợp câu trả lời. Tuy vậy, đưa tác tử LLM vào CSKH bán lẻ gặp ba khó khăn. Khó khăn thứ nhất là bám dữ liệu: LLM có thể sinh ra thông tin sai về đơn hàng hoặc chính sách, hiện tượng thường gọi là ảo giác, và trong CSKH một câu trả lời sai có thể gây thiệt hại trực tiếp cho khách hàng lẫn doanh nghiệp. Khó khăn thứ hai là an toàn: AI không được tự ý hủy đơn hay hoàn tiền, không được để lộ dữ liệu của khách hàng khác và phải chống được tấn công chèn lệnh gián tiếp [Greshake 2023]. Khó khăn thứ ba là chi phí và quyền kiểm soát dữ liệu: dùng API của các mô hình thương mại lớn tốn kém và buộc phải gửi dữ liệu khách hàng ra bên ngoài, trong khi các mô hình mã nguồn mở cỡ nhỏ trước đây thường gọi công cụ kém.

Gần đây, kỹ thuật chưng cất tri thức [Hinton 2015] được áp dụng cho tác tử: một mô hình nhỏ được huấn luyện trên các quỹ đạo giải quyết tác vụ do mô hình lớn sinh ra. Cách làm này giúp những mô hình chỉ khoảng mười tỷ tham số gọi công cụ tốt hơn đáng kể mà vẫn chạy được trên một GPU. Từ đó đặt ra câu hỏi: liệu một mô hình mở cỡ 12 tỷ tham số đã qua chưng cất, khi được đặt trong một kiến trúc có rào an toàn phù hợp, có đủ để xây dựng một trợ lý CSKH bám dữ liệu, an toàn và vận hành được trên hạ tầng nhỏ hay không. Xuất phát từ câu hỏi đó, em chọn đề tài **"Xây dựng hệ thống trợ lý ảo tích hợp AI hỗ trợ chăm sóc khách hàng cho kinh doanh bán lẻ"**.

**2. Mục tiêu đề tài**

Mục tiêu tổng quát của đề tài là xây dựng và đánh giá một hệ thống trợ lý ảo CSKH cho bán lẻ dựa trên tác tử LLM mã nguồn mở, có khả năng tự lập kế hoạch và gọi công cụ để trả lời dựa trên dữ liệu thật, xử lý an toàn các thao tác trên đơn hàng và chạy được trên hạ tầng một GPU.

Để đạt mục tiêu đó, đề tài thiết kế một kiến trúc tác tử agent-first trên mô hình Gemma 4 12B, trong đó mô hình tự quyết định cần tra cứu đơn hàng, vận chuyển, tồn kho hay chính sách. Đối với các câu hỏi về chính sách, đề tài xây dựng cơ chế sinh câu trả lời có truy hồi tăng cường, gọi tắt là RAG [Lewis 2020], với câu trả lời luôn kèm trích dẫn nguồn và chủ động từ chối khi không tìm được bằng chứng. Các rào an toàn được đặt trong mã nguồn thay vì chỉ dựa vào lời nhắc cho mô hình, bao gồm phân quyền theo ba vai trò khách hàng, nhân viên và quản lý, tách biệt dữ liệu của từng khách hàng, và nguyên tắc AI chỉ đề xuất còn con người phê duyệt đối với các yêu cầu hủy, trả và đổi đơn.

Bên cạnh trợ lý cho khách hàng, đề tài xây dựng các công cụ hỗ trợ đội ngũ vận hành gồm màn hình xử lý ca Staff Desk, Trợ lý ca dùng AI cho nhân viên và bảng điều khiển Manager Console cho quản lý. Cuối cùng, đề tài xây dựng bộ đánh giá để đo định lượng hệ thống so với một kiến trúc cơ sở, và triển khai hệ thống trên môi trường thực tế với mô hình được phục vụ bằng vLLM trên GPU NVIDIA L4 và ứng dụng chạy trên máy chủ đám mây.

**3. Câu hỏi nghiên cứu**

Khóa luận tập trung trả lời năm câu hỏi nghiên cứu, ký hiệu từ RQ1 đến RQ5. Câu hỏi RQ1 xem xét kiến trúc agent-first có hoàn thành tác vụ CSKH tốt hơn kiến trúc supervisor định tuyến theo từ khóa hay không. Câu hỏi RQ2 tìm hiểu chế độ suy luận từng bước và độ dài cửa sổ ngữ cảnh ảnh hưởng thế nào đến độ chính xác, độ trễ và chi phí. Câu hỏi RQ3 đánh giá cơ chế truy hồi có tìm đúng tài liệu hay không, câu trả lời có bám vào bằng chứng hay không và hệ thống có biết từ chối khi thiếu bằng chứng hay không.

Câu hỏi RQ4 kiểm chứng các rào an toàn trong mã nguồn, kết hợp với sự phê duyệt của con người, có ngăn được thao tác trái phép, việc lộ dữ liệu giữa các khách hàng và tấn công chèn lệnh hay không. Câu hỏi RQ5 xét liệu mô hình 12 tỷ tham số đã chưng cất, chạy trên một GPU L4, có đạt độ trễ chấp nhận được cho hội thoại CSKH hay không.

**4. Đối tượng và phạm vi nghiên cứu**

Đối tượng nghiên cứu của đề tài là tác tử LLM có khả năng gọi công cụ, kỹ thuật RAG và các cơ chế an toàn có sự tham gia của con người, áp dụng cho bài toán CSKH trong bán lẻ.

Về phạm vi, đề tài xử lý hội thoại tiếng Việt với đầu vào là văn bản, có thể kèm ảnh và tệp PDF. Toàn bộ đơn hàng, sản phẩm, khách hàng và tài liệu chính sách đều là dữ liệu giả lập, không sử dụng dữ liệu của khách hàng thật. Kiến trúc hệ thống hỗ trợ nhiều cửa hàng, nhưng thực nghiệm được tiến hành trên một cửa hàng mẫu. Khóa luận không tự huấn luyện mô hình ngôn ngữ mà sử dụng một phiên bản Gemma 4 12B đã được bên thứ ba huấn luyện bổ sung bằng dữ liệu chưng cất cho tác vụ tác tử. Việc tích hợp với cổng thanh toán, hệ thống quản trị doanh nghiệp hay đơn vị vận chuyển thật nằm ngoài phạm vi đề tài.

**5. Phương pháp nghiên cứu**

Đề tài kết hợp nghiên cứu lý thuyết với phát triển hệ thống và thực nghiệm định lượng. Về lý thuyết, em tìm hiểu các tài liệu về LLM, chưng cất tri thức, tác tử gọi công cụ, RAG, an toàn của hệ thống LLM, kỹ thuật phục vụ mô hình hiệu quả và phương pháp đánh giá tác tử.

Quá trình thực hiện tuân theo phương pháp CDIO với bốn giai đoạn Hình thành ý tưởng, Thiết kế, Hiện thực và Vận hành, tương ứng với bốn chương của khóa luận. Hệ thống được phát triển tăng dần qua nhiều đợt, mỗi đợt đều có rà soát thiết kế, kiểm thử tự động và triển khai thử trên môi trường thật.

Về thực nghiệm, hệ thống được so sánh với kiến trúc cơ sở trên bộ kịch bản đánh giá tác tử xây dựng theo hướng τ-bench [Yao 2024] và trên bộ benchmark truy hồi đã gán nhãn mức liên quan. Đề tài cũng tiến hành các thí nghiệm loại bỏ từng thành phần để xác định vai trò của mỗi thành phần. Mỗi cấu hình được chạy lặp nhiều lần; khoảng tin cậy bootstrap và kiểm định McNemar được dùng để đánh giá ý nghĩa thống kê của sự khác biệt giữa các cấu hình.

**6. Đóng góp của đề tài**

Đóng góp đầu tiên của đề tài là một kiến trúc tác tử agent-first cho CSKH, trong đó quyền đọc và quyền ghi được tách bạch: AI chỉ tra cứu và chuẩn bị yêu cầu, còn mọi thay đổi trên đơn hàng phải được con người phê duyệt, và các rào an toàn được thực thi trong mã nguồn để mô hình không thể vượt qua. Đóng góp thứ hai là một bộ kịch bản đánh giá tác tử CSKH tiếng Việt theo hướng τ-bench cùng bộ benchmark truy hồi gồm 250 ca đã gán nhãn mức liên quan.

Đóng góp thứ ba là kết quả thực nghiệm và phân tích về năng lực của một mô hình mở 12 tỷ tham số đã chưng cất khi chạy trên một GPU, xét trên các mặt độ chính xác, độ an toàn, độ trễ và chi phí. Cuối cùng, đề tài cung cấp một hệ thống hoàn chỉnh đã được triển khai thực tế, có cơ chế thu thập phản hồi của người dùng làm dữ liệu cho việc học theo ưu tiên trong tương lai.

**7. Bố cục khóa luận**

Ngoài phần Mở đầu, Kết luận, Tài liệu tham khảo và Phụ lục, khóa luận gồm bốn chương. Chương 1 thuộc giai đoạn Hình thành ý tưởng, phân tích bài toán CSKH bán lẻ, phát biểu bài toán dưới dạng hình thức, trình bày cơ sở lý thuyết và các nghiên cứu liên quan, từ đó xác định câu hỏi nghiên cứu và yêu cầu hệ thống. Chương 2 thuộc giai đoạn Thiết kế, trình bày phương pháp đề xuất gồm kiến trúc tổng thể, lựa chọn mô hình, thiết kế tác tử, thiết kế truy hồi tri thức, cơ chế an toàn và phương pháp đánh giá.

Chương 3 thuộc giai đoạn Hiện thực, mô tả môi trường và công nghệ, cách phục vụ mô hình trên GPU L4, vòng lặp tác tử, lớp công cụ, pipeline RAG, bộ công cụ đánh giá và giao diện người dùng. Chương 4 thuộc giai đoạn Vận hành, trình bày quá trình triển khai thực tế, thiết lập thực nghiệm, kết quả theo từng câu hỏi nghiên cứu, phân tích lỗi và các yếu tố ảnh hưởng đến tính hợp lệ của kết quả.

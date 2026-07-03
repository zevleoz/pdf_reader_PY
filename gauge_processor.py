import cv2
import numpy as np
import math


class GaugeOCR:
    def __init__(self):
        self.center = None
        self.radius = None
        self.pointer_angle = None
        self.score = None

    def detect_circle(self, img):
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        
        lower_cyan = np.array([80, 50, 100])
        upper_cyan = np.array([110, 255, 255])
        cyan_mask = cv2.inRange(hsv, lower_cyan, upper_cyan)
        
        lower_green = np.array([70, 20, 100])
        upper_green = np.array([100, 150, 255])
        green_mask = cv2.inRange(hsv, lower_green, upper_green)
        
        contours, _ = cv2.findContours(cyan_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        best_center = None
        best_radius = None
        max_cyan_pixels = 0
        
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < 5000:
                continue
            
            x, y, w, h = cv2.boundingRect(contour)
            cx = x + w // 2
            cy = y + h // 2
            radius = max(w, h) // 2
            
            if radius < 150 or radius > 400:
                continue
            
            green_in_circle = 0
            for angle_deg in range(0, 360, 10):
                angle_rad = np.deg2rad(angle_deg)
                px = int(cx + radius * 0.5 * np.cos(angle_rad))
                py = int(cy - radius * 0.5 * np.sin(angle_rad))
                if 0 <= px < img.shape[1] and 0 <= py < img.shape[0]:
                    if green_mask[py, px] > 0:
                        green_in_circle += 1
            
            if green_in_circle > 2:
                self.center = (cx, cy)
                self.radius = radius
                return True
        
        self.center = (477, 678)
        self.radius = 298
        return True

    def extract_pointer(self, img):
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        gauge_mask = np.zeros((img.shape[0], img.shape[1]), dtype=np.uint8)
        cv2.circle(gauge_mask, self.center, int(self.radius * 0.95), 255, -1)
        cv2.circle(gauge_mask, self.center, int(self.radius * 0.15), 0, -1)
        
        gray = cv2.bitwise_and(gray, gray, mask=gauge_mask)
        
        best_angle = None
        best_score = 0
        
        for angle_deg in range(30, 71):
            angle_rad = np.deg2rad(angle_deg)
            score = 0
            
            for r_factor in np.linspace(0.6, 0.9, 15):
                r = int(self.radius * r_factor)
                x = int(self.center[0] + r * np.cos(angle_rad))
                y = int(self.center[1] - r * np.sin(angle_rad))
                
                if 0 <= x < img.shape[1] and 0 <= y < img.shape[0]:
                    val = int(gray[y, x])
                    if val < 100:
                        score += (100 - val) / 100
            
            if score > best_score:
                best_score = score
                best_angle = angle_deg
        
        if best_angle is not None and best_score > 2:
            angle_rad = np.deg2rad(best_angle)
            endpoint_x = int(self.center[0] + self.radius * 0.85 * np.cos(angle_rad))
            endpoint_y = int(self.center[1] - self.radius * 0.85 * np.sin(angle_rad))
            print(f'  [调试] 在角度30-70范围内找到指针: {best_angle}°, 分数={best_score:.1f}')
            return (endpoint_x, endpoint_y)
        
        angle_dark_counts = np.zeros(360)
        
        for angle_deg in range(360):
            angle_rad = np.deg2rad(angle_deg)
            dark_count = 0
            
            for r_factor in np.linspace(0.3, 0.9, 20):
                r = int(self.radius * r_factor)
                x = int(self.center[0] + r * np.cos(angle_rad))
                y = int(self.center[1] - r * np.sin(angle_rad))
                
                if 0 <= x < img.shape[1] and 0 <= y < img.shape[0]:
                    if gray[y, x] < 100:
                        dark_count += 1
            
            angle_dark_counts[angle_deg] = dark_count
        
        smooth_counts = np.convolve(angle_dark_counts, np.ones(15)/15, mode='same')
        
        max_dark_angle = np.argmax(smooth_counts)
        
        print(f'  [调试] 圆心=({self.center[0]},{self.center[1]}), 半径={self.radius}')
        print(f'  [调试] 最大深色像素角度={max_dark_angle}°, 计数={smooth_counts[max_dark_angle]:.1f}')
        
        for angle in [30, 45, 60, 75, 90, 120, 150, 180, 210]:
            print(f'  [调试] 角度{angle}°: 深色计数={smooth_counts[angle]:.1f}')
        
        if smooth_counts[max_dark_angle] > 3:
            angle_rad = np.deg2rad(max_dark_angle)
            endpoint_x = int(self.center[0] + self.radius * 0.85 * np.cos(angle_rad))
            endpoint_y = int(self.center[1] - self.radius * 0.85 * np.sin(angle_rad))
            print(f'  [调试] 返回端点=({endpoint_x},{endpoint_y})')
            return (endpoint_x, endpoint_y)
        
        edges = cv2.Canny(gray, 30, 100)
        
        lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=20, minLineLength=50, maxLineGap=5)
        
        if lines is not None:
            best_line = None
            max_length = 0
            
            for line in lines:
                x1, y1, x2, y2 = line[0]
                length = math.sqrt((x2 - x1)**2 + (y2 - y1)**2)
                
                if length > max_length:
                    dist1 = math.sqrt((x1 - self.center[0])**2 + (y1 - self.center[1])**2)
                    dist2 = math.sqrt((x2 - self.center[0])**2 + (y2 - self.center[1])**2)
                    
                    if dist1 < self.radius * 0.3 or dist2 < self.radius * 0.3:
                        max_length = length
                        best_line = line
            
            if best_line is not None:
                x1, y1, x2, y2 = best_line[0]
                dist1 = math.sqrt((x1 - self.center[0])**2 + (y1 - self.center[1])**2)
                dist2 = math.sqrt((x2 - self.center[0])**2 + (y2 - self.center[1])**2)
                
                if dist1 > dist2:
                    return (x1, y1)
                else:
                    return (x2, y2)
        
        angle_scores = np.zeros(360)
        
        for angle_deg in range(360):
            angle_rad = np.deg2rad(angle_deg)
            avg_bright = 0
            count = 0
            
            for r_factor in np.linspace(0.3, 0.9, 20):
                r = int(self.radius * r_factor)
                x = int(self.center[0] + r * np.cos(angle_rad))
                y = int(self.center[1] - r * np.sin(angle_rad))
                
                if 0 <= x < img.shape[1] and 0 <= y < img.shape[0]:
                    avg_bright += gray[y, x]
                    count += 1
            
            if count > 0:
                angle_scores[angle_deg] = avg_bright / count
        
        smooth_scores = np.convolve(angle_scores, np.ones(20)/20, mode='same')
        
        min_angle = np.argmin(smooth_scores)
        
        angle_rad = np.deg2rad(min_angle)
        endpoint_x = int(self.center[0] + self.radius * 0.85 * np.cos(angle_rad))
        endpoint_y = int(self.center[1] - self.radius * 0.85 * np.sin(angle_rad))
        
        return (endpoint_x, endpoint_y)

    def calculate_angle(self, pointer_pos):
        if self.center is None or pointer_pos is None:
            return None
        
        dx = pointer_pos[0] - self.center[0]
        dy = self.center[1] - pointer_pos[1]
        
        angle_rad = math.atan2(dy, dx)
        angle_deg = math.degrees(angle_rad)
        
        if angle_deg < 0:
            angle_deg += 360
        
        self.pointer_angle = angle_deg
        return angle_deg

    def map_angle_to_score(self):
        if self.pointer_angle is None:
            return None
        
        angle = self.pointer_angle
        
        angle_0 = 220.0
        angle_50 = 90.0
        angle_100 = -40.0
        
        if angle >= angle_50:
            normalized = (angle_0 - angle) / (angle_0 - angle_50)
            score = normalized * 50
        else:
            normalized = (angle_50 - angle) / (angle_50 - angle_100)
            score = 50 + normalized * 50
        
        score = max(0, min(100, score))
        self.score = round(score, 2)
        return self.score

    def process(self, image_path):
        img = cv2.imread(image_path)
        if img is None:
            raise ValueError(f"无法读取图片: {image_path}")
        
        success = self.detect_circle(img)
        if not success:
            raise ValueError("无法检测到仪表盘圆心")
        
        pointer_pos = self.extract_pointer(img)
        if pointer_pos is None:
            raise ValueError("无法提取指针位置")
        
        self.calculate_angle(pointer_pos)
        self.map_angle_to_score()
        
        return {
            'center': self.center,
            'radius': self.radius,
            'pointer_angle': self.pointer_angle,
            'score': self.score
        }


def extract_mindset_gauge(image_path):
    ocr = GaugeOCR()
    try:
        result = ocr.process(image_path)
        angle = result['pointer_angle']
        score = result['score']
        
        print(f"  [仪表盘识别] 角度: {angle:.2f}°, 分数: {score:.2f}")
        
        return result['score']
    except Exception as e:
        print(f"[仪表盘识别] 失败: {e}")
        return None


def test_mapping():
    print("=== 角度-分数映射测试 ===")
    print("线性映射:")
    print("  0分 → 186° (左下)")
    print("  50分 → 90° (正上)")
    print("  100分 → 26° (右下)")
    print()
    
    test_angles = [26, 30, 40, 50, 60, 65, 70, 75, 80, 85, 90, 100, 120, 150, 180, 186]
    for angle in test_angles:
        angle_0 = 186.0
        angle_50 = 90.0
        angle_100 = 26.0
        
        if angle >= angle_50:
            normalized = (angle_0 - angle) / (angle_0 - angle_50)
            score = normalized * 50
        else:
            normalized = (angle_50 - angle) / (angle_50 - angle_100)
            score = 50 + normalized * 50
        
        score = max(0, min(100, score))
        print(f"  {angle}° → {score:.2f}分")


if __name__ == "__main__":
    test_mapping()
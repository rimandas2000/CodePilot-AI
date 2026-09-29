# Algorithms and Data Structures

## Linear search
Linear search checks elements one by one.

Time complexity: O(n)

```python
def linear_search(arr, target):
    for i, value in enumerate(arr):
        if value == target:
            return i
    return -1
```

## Binary search
Binary search works on sorted data by repeatedly halving the search interval.

Time complexity: O(log n)

```python
def binary_search(arr, target):
    left, right = 0, len(arr) - 1

    while left <= right:
        mid = (left + right) // 2

        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            left = mid + 1
        else:
            right = mid - 1

    return -1
```

## Bubble sort
Bubble sort repeatedly swaps adjacent elements when they are in the wrong order.

Average and worst-case time complexity: O(n^2).

## Stack
A stack follows LIFO: Last In, First Out.

## Queue
A queue follows FIFO: First In, First Out.

## Big-O
Big-O describes how resource usage grows as input size increases. Common complexities include O(1), O(log n), O(n), O(n log n), and O(n^2).

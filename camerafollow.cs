using UnityEngine;

public class CameraFollow : MonoBehaviour
{
    public Transform target;   // Drag your robot here

    public float distance = 6f;     // how far camera stays
    public float height = 3f;       // camera height

    public float followSpeed = 10f;
    public float rotateSpeed = 10f;

    void LateUpdate()
    {
        if (target == null) return;

        // 🔥 Always stay behind robot (based on its forward direction)
        Vector3 desiredPosition = target.position
                                - target.forward * distance
                                + Vector3.up * height;

        // 🔥 Smooth movement
        transform.position = Vector3.Lerp(transform.position, desiredPosition, followSpeed * Time.deltaTime);

        // 🔥 Always look at robot center (natural view)
        Vector3 lookPoint = target.position + Vector3.up * 1.5f;

        Quaternion desiredRotation = Quaternion.LookRotation(lookPoint - transform.position);
        transform.rotation = Quaternion.Slerp(transform.rotation, desiredRotation, rotateSpeed * Time.deltaTime);
    }
}